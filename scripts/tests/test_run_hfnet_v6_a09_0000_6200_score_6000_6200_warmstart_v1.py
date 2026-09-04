#!/usr/bin/env python3
"""Process-free tests for the A09 0..6200 / score 6000..6200 runner."""

from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_a09_0000_6200_score_6000_6200_warmstart_v1 as runner


def _stamps() -> list[int]:
    return [1_000_000_000_000_000_000 + index * 50_000_000 for index in range(6201)]


def _pose_line(stamp: int) -> str:
    return f"{stamp} 0 0 0 0 0 0 1"


def _runtime_paths(root: Path) -> dict[str, Path]:
    result_dir = root / "result"
    result_dir.mkdir()
    return {
        "result_dir": result_dir,
        "stdout": root / "headless.stdout.log",
        "stderr": root / "headless.stderr.log",
        "score_trajectory": result_dir / "trajectory_score_source_6000_6200.txt",
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
        _pose_line(stamps[runner.SCORE_LOCAL_FIRST + 80]) + "\n", encoding="ascii"
    )
    paths["stdout"].write_text(log, encoding="utf-8")
    paths["stderr"].write_bytes(b"")


def _restore_namespaces(snapshots: list[tuple[object, dict[str, object]]]) -> None:
    for namespace, before in reversed(snapshots):
        current = vars(namespace)
        for key in set(current).difference(before):
            del current[key]
        current.update(before)


class A09WarmstartRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        adapter = runner.hardened.inherited
        supervisor = adapter.profile
        base = supervisor.base
        snapshots = [
            (runner.hardened, dict(vars(runner.hardened))),
            (adapter, dict(vars(adapter))),
            (supervisor, dict(vars(supervisor))),
            (base, dict(vars(base))),
        ]
        self.addCleanup(_restore_namespaces, snapshots)

    def test_exact_identity_mapping_boundaries_and_namespace(self) -> None:
        self.assertEqual(
            (runner.FEED_SOURCE_FIRST, runner.FEED_SOURCE_LAST, runner.FEED_COUNT),
            (0, 6200, 6201),
        )
        self.assertEqual(
            (runner.FEED_LOCAL_FIRST, runner.FEED_LOCAL_LAST), (0, 6200)
        )
        self.assertEqual(
            (runner.SCORE_SOURCE_FIRST, runner.SCORE_SOURCE_LAST, runner.SCORE_COUNT),
            (6000, 6200, 201),
        )
        self.assertEqual(
            (runner.SCORE_LOCAL_FIRST, runner.SCORE_LOCAL_LAST), (6000, 6200)
        )
        self.assertEqual(runner.LOCAL_TO_SOURCE_OFFSET, 0)
        self.assertEqual(runner.SOURCE_TO_LOCAL_OFFSET, 0)
        self.assertEqual(runner.PREROLL_LAST_NS, 1542889045971818320)
        self.assertEqual(runner.SCORE_FIRST_NS, 1542889046021625712)
        self.assertIn("old_frozen_positive_windows", str(runner.ATTEMPT))
        self.assertEqual(runner.TIMEOUT_SECONDS, 900)

    def test_every_captured_supervisor_function_has_exact_frozen_a05_origin(self) -> None:
        self.assertTrue(runner._STRICT_PROFILE_CAPTURE_READY)
        for expected_name, function in runner._CAPTURED_A05_FUNCTIONS.items():
            with self.subTest(expected_name=expected_name):
                self.assertTrue(
                    runner._exact_python_function_origin(
                        function,
                        module=runner._EXPECTED_A05_MODULE,
                        name=expected_name,
                        filename=runner._EXPECTED_A05_FILE,
                    )
                )

    def test_a08_facade_configured_before_a09_import_fails_closed(self) -> None:
        from scripts import (
            run_hfnet_v6_a08_0000_4660_score_4500_4660_warmstart_v1 as a08,
        )

        a08.configure_profile()
        specification = importlib.util.spec_from_file_location(
            "a09_contaminated_import_probe", runner.__file__
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        probe = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(probe)
        self.assertFalse(probe._STRICT_PROFILE_CAPTURE_READY)
        with self.assertRaisesRegex(
            runner.hardened.inherited.profile.base.ContractError,
            "A09_STRICT_PROFILE_CAPTURE_CONTAMINATED_BY_PRIOR_OVERLAY",
        ):
            probe.configure_profile()

    def test_selection_and_runability_only_boundary_are_explicit(self) -> None:
        selection = runner._expected_prepared_selection()
        self.assertEqual(selection["feed_source_frame_indices_inclusive"], [0, 6200])
        self.assertEqual(selection["feed_local_frame_indices_inclusive"], [0, 6200])
        self.assertEqual(selection["score_source_frame_indices_inclusive"], [6000, 6200])
        self.assertEqual(selection["score_local_frame_indices_inclusive"], [6000, 6200])
        self.assertEqual(selection["preroll_camera_count"], 6000)
        self.assertTrue(selection["source_and_local_indices_are_identical"])
        boundary = runner._expected_comparison_boundary()
        self.assertTrue(boundary["runability_only"])
        self.assertFalse(boundary["accuracy_gate_open"])
        self.assertFalse(boundary["runtime_or_realtime_claim_permitted"])
        self.assertTrue(boundary["timeout_is_safety_ceiling_not_runtime_measurement"])
        self.assertFalse(boundary["formal_resource_contract_relaxed_for_todesk_or_unrelated_ros"])

    def test_historical_positive_evidence_is_revalidated_from_frozen_selector(self) -> None:
        observed = runner.validate_historical_evidence_authority()
        self.assertEqual(set(observed), runner.HISTORICAL_EVIDENCE_REQUIRED_KEYS)
        self.assertTrue(all(row["size_bytes"] > 0 for row in observed.values()))

    def test_pending_post_materialization_pins_fail_closed(self) -> None:
        attempt = self.root / "attempt_001"
        with mock.patch.object(runner, "ATTEMPT", attempt), mock.patch.object(
            runner, "INPUT_AUDIT_PIN_READY", False
        ):
            with self.assertRaisesRegex(
                runner.hardened.inherited.profile.base.ContractError,
                "A09_IDENTITY_PIN_PENDING",
            ):
                runner.validate_materialization_stage_authority()
            self.assertIn("INPUT_AUDIT", runner._pending_stage_pins())
        self.assertFalse(attempt.exists())

    def test_pose_parser_keeps_source_and_local_indices_identical(self) -> None:
        stamps = _stamps()
        trajectory = self.root / "trajectory.txt"
        trajectory.write_text(
            _pose_line(stamps[runner.SCORE_LOCAL_FIRST]) + "\n", encoding="ascii"
        )
        value = runner._parse_pose_rows(trajectory, stamps)
        self.assertTrue(value["valid"])
        row = value["rows"][0]
        self.assertEqual(row["local_camera_index"], 6000)
        self.assertEqual(row["source_camera_index"], 6000)

    def test_strict_201_pass_writes_read_only_no_clobber_crop(self) -> None:
        stamps = _stamps()
        path_map = _runtime_paths(self.root)
        _write_complete_outputs(path_map, stamps, _good_log())
        with mock.patch.object(runner, "selected_timestamps", return_value=stamps), mock.patch.object(
            runner, "paths", return_value=path_map
        ):
            result = runner.score_adjudication(_clean_value())
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"]["pose_count"], 201)
        self.assertTrue(result["score"]["exact_201_of_201_contiguous"])
        self.assertEqual(result["score"]["first_source_index"], 6000)
        self.assertEqual(result["score"]["last_source_index"], 6200)
        crop = path_map["score_trajectory"]
        self.assertEqual(len(crop.read_text(encoding="ascii").splitlines()), 201)
        self.assertEqual(os.stat(crop).st_mode & 0o777, 0o444)
        with self.assertRaises(FileExistsError):
            runner.hardened._write_exclusive(crop, b"no-clobber\n")

    def test_missing_pose_keyframe_init_or_clean_state_fails_without_crop(self) -> None:
        cases = (
            ("missing_pose", None),
            ("missing_boundary", None),
            ("no_score_keyframe", None),
            ("score_reinit", f"Init frame id: {runner.SCORE_LOCAL_FIRST}"),
            (
                "score_reset",
                "SYSTEM-> Reseting active map\n"
                f"mnFirstFrameId = {runner.SCORE_LOCAL_FIRST}",
            ),
            ("unresolved_reset", "SYSTEM-> Reseting active map"),
            ("no_pre_score_init", None),
        )
        for case_index, (label, extra) in enumerate(cases):
            with self.subTest(label=label):
                root = self.root / str(case_index)
                root.mkdir()
                stamps = _stamps()
                path_map = _runtime_paths(root)
                _write_complete_outputs(path_map, stamps, _good_log())
                if label == "missing_pose":
                    trajectory = path_map["result_dir"] / "trajectory.txt"
                    rows = trajectory.read_text(encoding="ascii").splitlines()
                    del rows[50]
                    trajectory.write_text("\n".join(rows) + "\n", encoding="ascii")
                elif label == "missing_boundary":
                    trajectory = path_map["result_dir"] / "trajectory.txt"
                    rows = trajectory.read_text(encoding="ascii").splitlines()
                    trajectory.write_text("\n".join(rows[1:]) + "\n", encoding="ascii")
                elif label == "no_score_keyframe":
                    (path_map["result_dir"] / "trajectory_keyframe.txt").write_text(
                        _pose_line(stamps[runner.SCORE_LOCAL_FIRST - 1]) + "\n",
                        encoding="ascii",
                    )
                elif label == "no_pre_score_init":
                    path_map["stdout"].write_text(
                        "\n".join(_good_log().splitlines()[2:]), encoding="utf-8"
                    )
                else:
                    path_map["stdout"].write_text(_good_log(str(extra)), encoding="utf-8")
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=path_map):
                    result = runner.score_adjudication(_clean_value())
                self.assertFalse(result["passed"])
                self.assertFalse(path_map["score_trajectory"].exists())

    def test_unreaped_child_rejects_outputs_before_any_parse_or_crop(self) -> None:
        value = _clean_value()
        value["execution"]["child_reaped_before_post_audit"] = False
        with mock.patch.object(
            runner, "selected_timestamps", side_effect=AssertionError("must not parse")
        ):
            result = runner.score_adjudication(value)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_codes"], ["CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED"])

    def test_configure_wires_hardened_one_shot_supervisor_without_start(self) -> None:
        runner.configure_profile()
        adapter = runner.hardened.inherited
        adapter.configure_profile()
        adapter.profile.configure_base()
        base = adapter.profile.base
        self.assertEqual(base.RUNNER, runner.RUNNER)
        self.assertEqual(base.SOURCE_ROOT, runner.INPUT_ROOT)
        self.assertEqual(base.SOURCE_FIRST, 0)
        self.assertEqual(base.SOURCE_LAST, 6200)
        self.assertEqual(base.CAMERA_COUNT, 6201)
        self.assertIs(base.atomic_json, runner.profile_atomic_json)
        self.assertIs(base.run, runner.run_once)
        self.assertIs(adapter.profile.run_with_watchdog, runner.warm_run_with_watchdog)

    def test_prior_todesk_overlay_is_replaced_by_strict_formal_bindings(self) -> None:
        from scripts import (
            run_hfnet_v6_a05_0001_3700_score_3300_3700_todesk_corun_development_only_v1
            as corun,
        )

        base = runner.hardened.inherited.profile.base
        corun.configure_overlay()
        self.assertIs(base.resource_gate, corun.resource_gate)
        self.assertIs(runner.hardened._finalize_result_total, corun._finalize_result_total)
        self.assertIs(
            runner.hardened._minimal_terminal_failure, corun._minimal_terminal_failure
        )

        runner.configure_profile()
        self.assertIs(base.resource_gate, runner._STRICT_BASE_RESOURCE_GATE)
        self.assertIs(
            runner.hardened._finalize_result_total, runner._STRICT_FINALIZE_RESULT
        )
        self.assertIs(
            runner.hardened._minimal_terminal_failure,
            runner._STRICT_MINIMAL_TERMINAL_FAILURE,
        )
        self.assertFalse(
            runner._expected_comparison_boundary()[
                "formal_resource_contract_relaxed_for_todesk_or_unrelated_ros"
            ]
        )

    def test_claim_precedes_only_popen_and_popen_failure_is_terminal(self) -> None:
        runner.configure_profile()
        base = runner.hardened.inherited.profile.base
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
            "score_trajectory": result_dir / "trajectory_score_source_6000_6200.txt",
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
            runner.hardened.inherited._BOUND_POPEN_COUNT += 1
            raise RuntimeError("synthetic Popen failure")

        runner.hardened.inherited._BOUND_POPEN_COUNT = 0
        runner.hardened._CLAIM_CREATED_THIS_PROCESS = False
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

    def test_supervisor_has_one_popen_site_and_wrapper_has_none(self) -> None:
        wrapper_source = Path(runner.__file__).read_text(encoding="utf-8")
        hardened_source = runner.HARDENED_A05_RUNNER.read_text(encoding="utf-8")
        self.assertEqual(wrapper_source.count("base.subprocess.Popen("), 0)
        self.assertEqual(hardened_source.count("base.subprocess.Popen("), 1)
        self.assertIn("O_EXCL_CLAIM_BEFORE_ONLY_HFNET_POPEN", hardened_source)
        self.assertIn('"retry_performed": False', hardened_source)
        self.assertNotIn("for retry", (wrapper_source + hardened_source).lower())


if __name__ == "__main__":
    unittest.main()
