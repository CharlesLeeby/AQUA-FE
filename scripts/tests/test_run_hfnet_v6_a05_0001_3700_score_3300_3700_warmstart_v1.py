#!/usr/bin/env python3
"""Process-free contract tests for the A05 HFNet natural-history runner."""

from __future__ import annotations

import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_a05_0001_3700_score_3300_3700_warmstart_v1 as runner


def _stamps() -> list[int]:
    return [1_000_000_000_000_000_000 + index * 50_000_000 for index in range(3700)]


def _pose_line(stamp: int) -> str:
    return f"{stamp} 0 0 0 0 0 0 1"


def _runtime_paths(root: Path) -> dict[str, Path]:
    result_dir = root / "result"
    result_dir.mkdir()
    return {
        "result_dir": result_dir,
        "stdout": root / "headless.stdout.log",
        "stderr": root / "headless.stderr.log",
        "score_trajectory": result_dir / "trajectory_score_source_3300_3700.txt",
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


def _good_log(*extra: str) -> str:
    return "\n".join(
        (
            "Init frame id: 0",
            "Imu initialized",
            *extra,
            "Saving trajectory to synthetic/result/trajectory.txt ...",
            "There are 1 maps in the atlas",
            "  Map 0 has 42 KFs",
            "End of saving trajectory to synthetic/result/trajectory.txt ...",
        )
    )


def _write_complete_outputs(paths: dict[str, Path], stamps: list[int], log: str) -> None:
    (paths["result_dir"] / "trajectory.txt").write_text(
        "\n".join(
            _pose_line(stamps[index])
            for index in range(runner.SCORE_LOCAL_FIRST - 1, runner.SCORE_LOCAL_LAST + 1)
        )
        + "\n",
        encoding="ascii",
    )
    (paths["result_dir"] / "trajectory_keyframe.txt").write_text(
        _pose_line(stamps[runner.SCORE_LOCAL_FIRST + 100]) + "\n",
        encoding="ascii",
    )
    paths["stdout"].write_text(log, encoding="utf-8")
    paths["stderr"].write_bytes(b"")


def _restore_namespaces(snapshots: list[tuple[object, dict[str, object]]]) -> None:
    for namespace, before in reversed(snapshots):
        current = vars(namespace)
        for key in set(current).difference(before):
            del current[key]
        current.update(before)


class A05WarmstartRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_exact_source_local_mapping_and_namespaces(self) -> None:
        self.assertEqual(
            (runner.FEED_SOURCE_FIRST, runner.FEED_SOURCE_LAST, runner.FEED_COUNT),
            (1, 3700, 3700),
        )
        self.assertEqual(
            (runner.FEED_LOCAL_FIRST, runner.FEED_LOCAL_LAST),
            (0, 3699),
        )
        self.assertEqual(
            (runner.SCORE_SOURCE_FIRST, runner.SCORE_SOURCE_LAST, runner.SCORE_COUNT),
            (3300, 3700, 401),
        )
        self.assertEqual(
            (runner.SCORE_LOCAL_FIRST, runner.SCORE_LOCAL_LAST),
            (3299, 3699),
        )
        self.assertEqual(runner.LOCAL_TO_SOURCE_OFFSET, 1)
        self.assertEqual(runner.SOURCE_TO_LOCAL_OFFSET, -1)
        self.assertEqual(runner.PREROLL_LAST_NS, 1455214343489444000)
        self.assertEqual(runner.SCORE_FIRST_NS, 1455214343539451680)
        self.assertEqual(
            runner.paths()["score_trajectory"].name,
            "trajectory_score_source_3300_3700.txt",
        )
        self.assertEqual(
            runner.AUTHORIZATION_TOKEN,
            "HFNET_V6_A05_0001_3700_SCORE_3300_3700_WARMSTART_"
            "ATTEMPT_001_START_EXACTLY_ONCE",
        )

    def test_prepared_selection_and_accuracy_boundary_are_explicit(self) -> None:
        selection = runner._expected_prepared_selection()
        self.assertEqual(selection["feed_source_frame_indices_inclusive"], [1, 3700])
        self.assertEqual(selection["feed_local_frame_indices_inclusive"], [0, 3699])
        self.assertEqual(selection["score_source_frame_indices_inclusive"], [3300, 3700])
        self.assertEqual(selection["score_local_frame_indices_inclusive"], [3299, 3699])
        self.assertEqual(selection["preroll_camera_count"], 3299)
        self.assertTrue(selection["development_result_conditioned_selection"])
        boundary = runner._expected_comparison_boundary()
        self.assertTrue(boundary["runability_only"])
        self.assertFalse(boundary["accuracy_gate_open"])
        self.assertFalse(boundary["runtime_or_realtime_claim_permitted"])

    def test_unpinned_audit_rejects_before_attempt_namespace(self) -> None:
        temporary_attempt = self.root / "attempt_001"
        adapter = runner.inherited
        supervisor = adapter.profile
        base = supervisor.base
        snapshots = [
            (adapter, dict(vars(adapter))),
            (supervisor, dict(vars(supervisor))),
            (base, dict(vars(base))),
        ]
        self.addCleanup(_restore_namespaces, snapshots)
        with mock.patch.object(runner, "ATTEMPT", temporary_attempt), mock.patch.object(
            runner, "INPUT_AUDITOR_PIN_READY", False
        ), mock.patch.object(runner, "INPUT_AUDIT_PIN_READY", False):
            runner.configure_profile()
            adapter.configure_profile()
            supervisor.configure_base()
            with self.assertRaisesRegex(base.ContractError, "IDENTITY_PIN_PENDING"):
                base.prepare()
        self.assertFalse(temporary_attempt.exists())

    def test_selected_timestamps_pin_local_score_boundary(self) -> None:
        with mock.patch.object(runner, "validate_input_authority", return_value={}):
            stamps = runner.selected_timestamps()
        self.assertEqual(len(stamps), 3700)
        self.assertEqual(stamps[0], runner.FEED_FIRST_NS)
        self.assertEqual(stamps[runner.SCORE_LOCAL_FIRST - 1], runner.PREROLL_LAST_NS)
        self.assertEqual(stamps[runner.SCORE_LOCAL_FIRST], runner.SCORE_FIRST_NS)
        self.assertEqual(stamps[-1], runner.SCORE_LAST_NS)

    def test_pose_parser_records_both_index_spaces(self) -> None:
        stamps = _stamps()
        trajectory = self.root / "trajectory.txt"
        trajectory.write_text(
            _pose_line(stamps[runner.SCORE_LOCAL_FIRST]) + "\n", encoding="ascii"
        )
        value = runner._parse_pose_rows(trajectory, stamps)
        self.assertTrue(value["valid"])
        row = value["rows"][0]
        self.assertEqual(row["local_camera_index"], 3299)
        self.assertEqual(row["source_camera_index"], 3300)

    def test_prepared_launch_contract_rejects_drift(self) -> None:
        path_map = {
            "runtime_config": self.root / "runtime.yaml",
            "result_dir": self.root / "result",
            "subset_times": self.root / "times.txt",
        }
        identity = {"path": "synthetic", "size_bytes": 1, "sha256": "frozen"}
        controller = {"controller": identity}
        base = runner.inherited.profile.base
        prepared = {
            "schema_version": runner.PREPARED_SCHEMA,
            "status": "PREPARED_NOT_STARTED",
            "scientific_role": runner.SCIENTIFIC_ROLE,
            "claim_boundary": {
                "accuracy_evaluated": False,
                "superiority_claimed": False,
                "retry_permitted": False,
            },
            "selection": runner._expected_prepared_selection(),
            "input_authority": {
                "materialization_manifest": identity,
                "independent_audit_receipt": identity,
                "payload_sha256_excluding_manifest": runner.INPUT_PAYLOAD_SHA256,
            },
            "controller_authority": controller,
            "comparison_boundary": runner._expected_comparison_boundary(),
            "pins": {"runner": identity},
            "launch": {
                "argv": [
                    str(base.BINARY),
                    str(path_map["runtime_config"]),
                    str(path_map["result_dir"]) + "/",
                    str(runner.INPUT_ROOT),
                    str(path_map["subset_times"]),
                ],
                "timeout_seconds": runner.TIMEOUT_SECONDS,
                "maximum_popen_invocations": 1,
                "authorization_token": runner.AUTHORIZATION_TOKEN,
            },
        }
        with mock.patch.object(runner, "paths", return_value=path_map), mock.patch.object(
            runner, "_identity", return_value=identity
        ), mock.patch.object(runner, "validate_code_authority", return_value=controller):
            runner._validate_prepared_launch(prepared)
            for label, mutate in (
                ("selection", lambda value: value["selection"].__setitem__("score_camera_count", 400)),
                ("timeout", lambda value: value["launch"].__setitem__("timeout_seconds", 599)),
                ("token", lambda value: value["launch"].__setitem__("authorization_token", "wrong")),
                ("retry", lambda value: value["claim_boundary"].__setitem__("retry_permitted", True)),
            ):
                with self.subTest(label=label):
                    drifted = copy.deepcopy(prepared)
                    mutate(drifted)
                    with self.assertRaises(base.ContractError):
                        runner._validate_prepared_launch(drifted)

    def test_strict_401_pass_writes_read_only_score_crop(self) -> None:
        stamps = _stamps()
        paths = _runtime_paths(self.root)
        _write_complete_outputs(paths, stamps, _good_log())
        with mock.patch.object(runner, "selected_timestamps", return_value=stamps), mock.patch.object(
            runner, "paths", return_value=paths
        ):
            result = runner.score_adjudication(_clean_value())
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"]["pose_count"], 401)
        self.assertEqual(result["score"]["first_local_index"], 3299)
        self.assertEqual(result["score"]["first_source_index"], 3300)
        self.assertEqual(result["score"]["last_source_index"], 3700)
        crop = paths["score_trajectory"]
        self.assertEqual(len(crop.read_text(encoding="ascii").splitlines()), 401)
        self.assertEqual(os.stat(crop).st_mode & 0o777, 0o444)
        with self.assertRaises(FileExistsError):
            runner._write_exclusive(crop, b"no-clobber\n")

    def test_score_support_and_state_fail_closed_without_crop(self) -> None:
        cases = (
            ("missing_pose", None),
            ("score_reinit", f"Init frame id: {runner.SCORE_LOCAL_FIRST}"),
            (
                "score_reset",
                "SYSTEM-> Reseting active map\n"
                f"mnFirstFrameId = {runner.SCORE_LOCAL_FIRST}",
            ),
            ("no_pre_score_init", "NO_INIT_EVENT"),
        )
        for case_index, (label, extra) in enumerate(cases):
            with self.subTest(label=label):
                case_root = self.root / str(case_index)
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                _write_complete_outputs(paths, stamps, _good_log())
                if label == "missing_pose":
                    trajectory = paths["result_dir"] / "trajectory.txt"
                    rows = trajectory.read_text(encoding="ascii").splitlines()
                    del rows[101]
                    trajectory.write_text("\n".join(rows) + "\n", encoding="ascii")
                elif label == "no_pre_score_init":
                    paths["stdout"].write_text(
                        "\n".join(_good_log().splitlines()[2:]), encoding="utf-8"
                    )
                else:
                    paths["stdout"].write_text(_good_log(str(extra)), encoding="utf-8")
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=paths):
                    result = runner.score_adjudication(_clean_value())
                self.assertFalse(result["passed"])
                self.assertFalse(paths["score_trajectory"].exists())

    def test_claim_precedes_the_only_popen_and_failure_is_terminal(self) -> None:
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
            "score_trajectory": result_dir / "trajectory_score_source_3300_3700.txt",
        }
        prepared = {
            "launch": {"argv": ["synthetic-hfnet"]},
            "input_inventory": {"synthetic": True},
            "selection": runner._expected_prepared_selection(),
            "scientific_role": runner.SCIENTIFIC_ROLE,
        }
        calls: list[object] = []

        def fail_popen(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            self.assertTrue(path_map["claim"].is_file())
            claim = json.loads(path_map["claim"].read_text(encoding="utf-8"))
            self.assertEqual(claim["maximum_hfnet_elf_starts"], 1)
            self.assertFalse(claim["retry"])
            runner.inherited._BOUND_POPEN_COUNT += 1
            raise RuntimeError("synthetic Popen failure")

        old_count = runner.inherited._BOUND_POPEN_COUNT
        old_claim = runner._CLAIM_CREATED_THIS_PROCESS
        runner.inherited._BOUND_POPEN_COUNT = 0
        runner._CLAIM_CREATED_THIS_PROCESS = False
        self.addCleanup(setattr, runner.inherited, "_BOUND_POPEN_COUNT", old_count)
        self.addCleanup(setattr, runner, "_CLAIM_CREATED_THIS_PROCESS", old_claim)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner, "paths", return_value=path_map))
            stack.enter_context(mock.patch.object(runner, "check", return_value={"ready": True, "errors": []}))
            stack.enter_context(mock.patch.object(runner, "_validate_prepared_launch", return_value=None))
            stack.enter_context(
                mock.patch.object(
                    runner,
                    "runtime_authority_snapshot",
                    side_effect=lambda include_claim=False: {"include_claim": include_claim},
                )
            )
            stack.enter_context(
                mock.patch.object(
                    runner,
                    "local_cache_state",
                    return_value={"identity": {"sha256": "seed"}, "isolated": True},
                )
            )
            stack.enter_context(mock.patch.object(runner, "selected_timestamps", return_value=_stamps()))
            stack.enter_context(mock.patch.object(base, "load_prepared", return_value=prepared))
            stack.enter_context(mock.patch.object(base, "input_inventory", return_value={"synthetic": True}))
            stack.enter_context(mock.patch.object(base, "runtime_environment", return_value={}))
            stack.enter_context(mock.patch.object(base.subprocess, "Popen", side_effect=fail_popen))
            value = runner.run_once(runner.AUTHORIZATION_TOKEN)
        self.assertEqual(len(calls), 1)
        self.assertEqual(value["status"], "FAIL_DEVELOPMENT_RUNABILITY")
        self.assertTrue(path_map["claim"].is_file())
        self.assertTrue(path_map["result"].is_file())
        self.assertFalse(value["terminal_contract"]["retry_after_pass_or_fail"])
        self.assertTrue(value["terminal_contract"]["attempt_consumed"])

    def test_configure_wires_hardened_supervisor_without_start(self) -> None:
        adapter = runner.inherited
        supervisor = adapter.profile
        base = supervisor.base
        snapshots = [
            (adapter, dict(vars(adapter))),
            (supervisor, dict(vars(supervisor))),
            (base, dict(vars(base))),
        ]
        self.addCleanup(_restore_namespaces, snapshots)
        runner.configure_profile()
        adapter.configure_profile()
        supervisor.configure_base()
        self.assertEqual(base.RUNNER, runner.RUNNER)
        self.assertEqual(base.SOURCE_ROOT, runner.INPUT_ROOT)
        self.assertEqual(base.SOURCE_FIRST, runner.FEED_LOCAL_FIRST)
        self.assertEqual(base.SOURCE_LAST, runner.FEED_LOCAL_LAST)
        self.assertEqual(base.CAMERA_COUNT, runner.FEED_COUNT)
        self.assertIs(base.atomic_json, runner.profile_atomic_json)
        self.assertIs(base.run, runner.run_once)
        self.assertIs(supervisor.run_with_watchdog, runner.warm_run_with_watchdog)

    def test_atomic_terminal_publisher_is_no_replace(self) -> None:
        destination = self.root / "terminal.json"
        runner._publish_json_exclusive_atomic(destination, {"complete": True})
        self.assertEqual(os.stat(destination).st_mode & 0o777, 0o444)
        with self.assertRaises(FileExistsError):
            runner._publish_json_exclusive_atomic(destination, {"complete": False})

    def test_source_has_one_popen_site_and_no_retry_loop(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("base.subprocess.Popen("), 1)
        self.assertIn("O_EXCL_CLAIM_BEFORE_ONLY_HFNET_POPEN", source)
        self.assertIn('"retry_performed": False', source)
        self.assertNotIn("for retry", source.lower())


if __name__ == "__main__":
    unittest.main()
