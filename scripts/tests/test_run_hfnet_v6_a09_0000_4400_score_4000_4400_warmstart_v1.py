#!/usr/bin/env python3
"""Process-free tests for the A09 HFNet warm-start one-shot runner."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import json
from contextlib import ExitStack
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_v1 as runner


def _stamps() -> list[int]:
    return [1_000_000_000_000_000_000 + index * 50_000_000 for index in range(4401)]


def _pose_line(stamp: int) -> str:
    return f"{stamp} 0 0 0 0 0 0 1"


def _runtime_paths(root: Path) -> dict[str, Path]:
    result_dir = root / "result"
    result_dir.mkdir()
    return {
        "result_dir": result_dir,
        "stdout": root / "headless.stdout.log",
        "stderr": root / "headless.stderr.log",
        "score_trajectory": result_dir / "trajectory_score_4000_4400.txt",
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
        "\n".join(_pose_line(stamps[index]) for index in range(3999, 4401)) + "\n",
        encoding="ascii",
    )
    keyframes.write_text(_pose_line(stamps[4100]) + "\n", encoding="ascii")
    paths["stdout"].write_text(log, encoding="utf-8")
    paths["stderr"].write_bytes(b"")


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

    def test_exact_target_constants_and_no_legacy_literals(self) -> None:
        self.assertEqual((runner.FEED_FIRST, runner.FEED_LAST, runner.FEED_COUNT), (0, 4400, 4401))
        self.assertEqual((runner.SCORE_FIRST, runner.SCORE_LAST, runner.SCORE_COUNT), (4000, 4400, 401))
        self.assertEqual(runner.PREROLL_LAST_NS, 1542888945988866768)
        self.assertEqual(runner.SCORE_FIRST_NS, 1542888946038630384)
        self.assertEqual(runner.TIMEOUT_SECONDS, 600)
        self.assertEqual(runner.paths()["subset_times"].name, "cam0_times_0000_4400.txt")
        self.assertEqual(
            runner.paths()["score_trajectory"].name,
            "trajectory_score_4000_4400.txt",
        )
        self.assertEqual(
            runner.AUTHORIZATION_TOKEN,
            "HFNET_V6_A09_0000_4400_SCORE_4000_4400_WARMSTART_ATTEMPT_001_START_EXACTLY_ONCE",
        )
        forbidden = ("a" + "10", "24" + "00", "28" + "00")
        for source_path in (Path(runner.__file__), Path(__file__)):
            source = source_path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(token, source)

    def test_materialization_authority_and_outcome_freeze_are_bound(self) -> None:
        value = runner.validate_materialization_stage_authority()
        self.assertEqual(
            value["freeze"]["status"],
            "FROZEN_PASS_PREPARATION_ONLY_RUNNER_IMPLEMENTATION_PERMITTED",
        )
        self.assertEqual(
            value["freeze"]["authority_consumption"]["consumed_invocation_count"],
            1,
        )

    def test_materialization_outcome_semantic_drift_is_rejected(self) -> None:
        authority = json.loads(runner.MATERIALIZATION_AUTHORITY.read_text(encoding="utf-8"))
        freeze = json.loads(runner.MATERIALIZATION_FREEZE.read_text(encoding="utf-8"))
        freeze["authority_consumption"]["consumed_invocation_count"] = 0
        with mock.patch.object(runner.json, "loads", side_effect=[authority, freeze]):
            with self.assertRaises(runner.inherited.profile.base.ContractError):
                runner.validate_materialization_stage_authority()

    def test_provenance_identity_helper_rejects_any_drift(self) -> None:
        identity = runner._identity(runner.SELECTOR)
        self.assertEqual(
            runner._require_provenance_identity(identity, runner.SELECTOR, "SYNTHETIC"),
            identity,
        )
        drifted = dict(identity)
        drifted["size_bytes"] = int(drifted["size_bytes"]) + 1
        with self.assertRaises(runner.inherited.profile.base.ContractError):
            runner._require_provenance_identity(drifted, runner.SELECTOR, "SYNTHETIC")

    def test_selected_timestamps_pin_feed_score_and_boundary(self) -> None:
        with mock.patch.object(runner, "validate_input_authority", return_value={}):
            stamps = runner.selected_timestamps()
        self.assertEqual(len(stamps), 4401)
        self.assertEqual(stamps[0], runner.FEED_FIRST_NS)
        self.assertEqual(stamps[runner.SCORE_FIRST - 1], runner.PREROLL_LAST_NS)
        self.assertEqual(stamps[runner.SCORE_FIRST], runner.SCORE_FIRST_NS)
        self.assertEqual(stamps[-1], runner.FEED_LAST_NS)
        self.assertGreater(stamps[runner.SCORE_FIRST], stamps[runner.SCORE_FIRST - 1])

    def test_prepared_contract_is_exact_and_drift_fails_closed(self) -> None:
        path_map = {
            "runtime_config": self.root / "runtime.yaml",
            "result_dir": self.root / "result",
            "subset_times": self.root / "times.txt",
        }
        fixed_identity = {"path": "synthetic", "size_bytes": 1, "sha256": "frozen"}
        controller = {"controller": fixed_identity}
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
                "materialization_manifest": fixed_identity,
                "independent_audit_receipt": fixed_identity,
                "payload_sha256_excluding_manifest": runner.INPUT_PAYLOAD_SHA256,
            },
            "controller_authority": controller,
            "comparison_boundary": runner._expected_comparison_boundary(),
            "pins": {"runner": fixed_identity},
            "launch": {
                "argv": [
                    str(base.BINARY),
                    str(path_map["runtime_config"]),
                    str(path_map["result_dir"]) + "/",
                    str(runner.INPUT_ROOT),
                    str(path_map["subset_times"]),
                ],
                "timeout_seconds": 600,
                "maximum_popen_invocations": 1,
                "authorization_token": runner.AUTHORIZATION_TOKEN,
            },
        }
        with mock.patch.object(runner, "paths", return_value=path_map), mock.patch.object(
            runner, "_identity", return_value=fixed_identity
        ), mock.patch.object(runner, "validate_code_authority", return_value=controller):
            runner._validate_prepared_launch(prepared)
            mutations = (
                ("schema", lambda value: value.__setitem__("schema_version", "drift")),
                ("selection", lambda value: value["selection"].__setitem__("score_camera_count", 400)),
                ("authority", lambda value: value.__setitem__("controller_authority", {})),
                ("timeout", lambda value: value["launch"].__setitem__("timeout_seconds", 599)),
                ("token", lambda value: value["launch"].__setitem__("authorization_token", "wrong")),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    drifted = copy.deepcopy(prepared)
                    mutate(drifted)
                    with self.assertRaises(base.ContractError):
                        runner._validate_prepared_launch(drifted)

    def test_prepared_publication_includes_frozen_window_and_all_authorities(self) -> None:
        attempt = self.root / "attempt"
        path_map = {
            "prepared": attempt / "prepared_manifest.json",
            "claim": attempt / "process_start_claim.json",
            "result": attempt / "run_result.json",
        }
        fixed_identity = {"path": "synthetic", "size_bytes": 1, "sha256": "frozen"}
        controller = {
            "materialization_authority": fixed_identity,
            "materialization_outcome_freeze": fixed_identity,
        }
        published: list[object] = []
        value: dict[str, object] = {"claim_boundary": {}}
        with mock.patch.object(runner, "paths", return_value=path_map), mock.patch.object(
            runner, "_identity", return_value=fixed_identity
        ), mock.patch.object(runner, "validate_code_authority", return_value=controller), mock.patch.object(
            runner,
            "_publish_json_exclusive_atomic",
            side_effect=lambda path, payload: published.append((path, copy.deepcopy(payload))),
        ):
            runner.profile_atomic_json(path_map["prepared"], value)
        self.assertEqual(value["schema_version"], runner.PREPARED_SCHEMA)
        self.assertEqual(value["selection"], runner._expected_prepared_selection())
        self.assertEqual(value["controller_authority"], controller)
        self.assertEqual(len(published), 1)

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
        self.assertTrue(rows[0].startswith(str(stamps[4000])))
        self.assertTrue(rows[-1].startswith(str(stamps[4400])))
        self.assertEqual(os.stat(crop).st_mode & 0o777, 0o444)
        with self.assertRaises(FileExistsError):
            runner._write_exclusive(crop, b"must-not-overwrite\n")

    def test_prefix_reset_is_allowed_but_score_boundary_stays_continuous(self) -> None:
        stamps = _stamps()
        paths = _runtime_paths(self.root)
        _write_complete_outputs(
            paths,
            stamps,
            _good_log(
                "SYSTEM-> Reseting active map in monocular case",
                "mnFirstFrameId = 120",
                "Init frame id: 200",
            ),
        )
        with mock.patch.object(runner, "selected_timestamps", return_value=stamps), mock.patch.object(
            runner, "paths", return_value=paths
        ):
            result = runner.score_adjudication(_clean_value())
        self.assertTrue(result["passed"])
        self.assertEqual(result["runtime_log"]["score_window_reset_events"], [])

    def test_score_support_breaks_fail_closed_without_crop(self) -> None:
        cases = ("missing_boundary", "missing_score", "duplicate_score", "no_keyframe")
        for case_index, case in enumerate(cases):
            with self.subTest(case=case):
                case_root = self.root / f"support-{case_index}"
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                indices = list(range(runner.SCORE_FIRST - 1, runner.SCORE_LAST + 1))
                if case == "missing_boundary":
                    indices = indices[1:]
                elif case == "missing_score":
                    indices.remove(runner.SCORE_FIRST + 100)
                trajectory = paths["result_dir"] / "trajectory.txt"
                trajectory.write_text(
                    "\n".join(_pose_line(stamps[index]) for index in indices) + "\n",
                    encoding="ascii",
                )
                if case == "duplicate_score":
                    with trajectory.open("a", encoding="ascii") as stream:
                        stream.write(_pose_line(stamps[runner.SCORE_LAST]) + "\n")
                keyframes = paths["result_dir"] / "trajectory_keyframe.txt"
                keyframes.write_text(
                    "" if case == "no_keyframe" else _pose_line(stamps[runner.SCORE_FIRST + 100]) + "\n",
                    encoding="ascii",
                )
                paths["stdout"].write_text(_good_log(), encoding="utf-8")
                paths["stderr"].write_bytes(b"")
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=paths):
                    result = runner.score_adjudication(_clean_value())
                self.assertFalse(result["passed"])
                self.assertFalse(paths["score_trajectory"].exists())

    def test_execution_and_integrity_breaks_fail_closed_without_crop(self) -> None:
        mutations = (
            ("child", lambda value: value["execution"].__setitem__("child_reaped_before_post_audit", False)),
            ("return", lambda value: value["execution"].__setitem__("raw_returncode", 1)),
            ("timeout", lambda value: value["execution"].__setitem__("timed_out", True)),
            ("supervisor", lambda value: value["execution"].__setitem__("supervisor_error", "failure")),
            ("input", lambda value: value["integrity"].__setitem__("selected_input_unchanged", False)),
            ("model", lambda value: value["integrity"].__setitem__("local_onnx_unchanged", False)),
            ("runtime", lambda value: value["integrity"].__setitem__("runtime_authority_unchanged", False)),
            ("post", lambda value: value["integrity"].__setitem__("all_post_audits_complete", False)),
        )
        for case_index, (label, mutate) in enumerate(mutations):
            with self.subTest(label=label):
                case_root = self.root / f"execution-{case_index}"
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                _write_complete_outputs(paths, stamps, _good_log())
                value = _clean_value()
                mutate(value)
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=paths):
                    result = runner.score_adjudication(value)
                self.assertFalse(result["passed"])
                self.assertFalse(paths["score_trajectory"].exists())

    def test_final_atlas_and_save_breaks_fail_closed_without_crop(self) -> None:
        logs = (
            "\n".join(("Init frame id: 0", "Saving trajectory to x", "There are 1 maps in the atlas", "  Map 0 has 0 KFs", "End of saving trajectory to x")),
            "\n".join(("Init frame id: 0", "Saving trajectory to x", "There are 1 maps in the atlas", "  Map 0 has 42 KFs")),
            "\n".join(("Init frame id: 0", "Saving trajectory to x", "There are 2 maps in the atlas", "  Map 0 has 42 KFs", "End of saving trajectory to x")),
        )
        for case_index, log in enumerate(logs):
            with self.subTest(case=case_index):
                case_root = self.root / f"atlas-{case_index}"
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                _write_complete_outputs(paths, stamps, log)
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=paths):
                    result = runner.score_adjudication(_clean_value())
                self.assertFalse(result["passed"])
                self.assertFalse(paths["score_trajectory"].exists())

    def test_score_window_state_breaks_fail_closed(self) -> None:
        cases = (
            (
                f"SYSTEM-> Reseting active map in monocular case\nmnFirstFrameId = {runner.SCORE_FIRST}",
                "SCORE_WINDOW_ACTIVE_MAP_RESET",
            ),
            (f"Init frame id: {runner.SCORE_FIRST}", "SCORE_WINDOW_REINITIALIZATION"),
            (
                "SYSTEM-> Reseting active map in monocular case",
                "ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED",
            ),
            ("NO_INIT_EVENT", "NO_INITIALIZED_MAP_CARRIED_INTO_SCORE_WINDOW"),
        )
        for case_index, (extra_log, failure_code) in enumerate(cases):
            with self.subTest(failure_code=failure_code):
                case_root = self.root / str(case_index)
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                base_init = () if extra_log == "NO_INIT_EVENT" else ("Init frame id: 0",)
                visible_extra = () if extra_log == "NO_INIT_EVENT" else (extra_log,)
                _write_complete_outputs(
                    paths,
                    stamps,
                    "\n".join(
                        (
                            *base_init,
                            *visible_extra,
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

        self.assertEqual(adapter.RUNNER, runner.RUNNER)
        self.assertEqual(supervisor.RUNNER, runner.RUNNER)
        self.assertEqual(supervisor.base.RUNNER, runner.RUNNER)
        self.assertEqual(supervisor.base.SOURCE_ROOT, runner.INPUT_ROOT)
        self.assertEqual(adapter.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertEqual(supervisor.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertEqual(supervisor.base.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertIs(adapter.paths, runner.paths)
        self.assertIs(supervisor.paths, runner.paths)
        self.assertIs(supervisor.base.attempt_paths, runner.paths)
        self.assertIs(supervisor.base.atomic_json, runner.profile_atomic_json)
        self.assertIs(supervisor.bound_popen, adapter.bound_popen)
        self.assertIs(supervisor.base.run, runner.run_once)
        self.assertIs(supervisor.run_with_watchdog, runner.warm_run_with_watchdog)

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
            "score_trajectory": result_dir / "trajectory_score_4000_4400.txt",
        }
        prepared = {
            "launch": {"argv": ["synthetic-hfnet"]},
            "input_inventory": {"synthetic": True},
            "selection": {"score_source_frame_indices_inclusive": [4000, 4400]},
            "scientific_role": "DEVELOPMENT_ONLY_SYNTHETIC_TEST",
        }
        stamps = _stamps()
        popen_calls: list[object] = []

        def fail_popen(*args: object, **kwargs: object) -> object:
            popen_calls.append((args, kwargs))
            self.assertTrue(path_map["claim"].is_file())
            claim = json.loads(path_map["claim"].read_text(encoding="utf-8"))
            self.assertEqual(claim["schema_version"], runner.CLAIM_SCHEMA)
            self.assertEqual(claim["authorization_token"], runner.AUTHORIZATION_TOKEN)
            self.assertEqual(claim["maximum_hfnet_elf_starts"], 1)
            self.assertFalse(claim["retry"])
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

    def test_claim_commit_then_publication_exception_recovers_terminal_failure(self) -> None:
        base = runner.inherited.profile.base
        attempt = self.root / "claim-recovery"
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
            "score_trajectory": result_dir / "trajectory_score_4000_4400.txt",
        }
        prepared = {
            "launch": {"argv": ["synthetic-hfnet"]},
            "input_inventory": {"synthetic": True},
            "selection": runner._expected_prepared_selection(),
            "scientific_role": runner.SCIENTIFIC_ROLE,
        }
        old_count = runner.inherited._BOUND_POPEN_COUNT
        old_claim_state = runner._CLAIM_CREATED_THIS_PROCESS
        runner.inherited._BOUND_POPEN_COUNT = 0
        runner._CLAIM_CREATED_THIS_PROCESS = False
        self.addCleanup(setattr, runner.inherited, "_BOUND_POPEN_COUNT", old_count)
        self.addCleanup(setattr, runner, "_CLAIM_CREATED_THIS_PROCESS", old_claim_state)
        real_publish = runner._publish_json_exclusive_atomic
        claim_commits = 0

        def commit_then_raise(path: Path, value: object) -> None:
            nonlocal claim_commits
            real_publish(path, value)
            if path == path_map["claim"]:
                claim_commits += 1
                raise OSError("synthetic directory fsync failure after claim commit")

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner, "paths", return_value=path_map))
            stack.enter_context(mock.patch.object(runner, "check", return_value={"ready": True, "errors": []}))
            stack.enter_context(mock.patch.object(runner, "_validate_prepared_launch", return_value=None))
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
            stack.enter_context(mock.patch.object(base, "load_prepared", return_value=prepared))
            stack.enter_context(
                mock.patch.object(runner, "_publish_json_exclusive_atomic", side_effect=commit_then_raise)
            )
            value = runner.run_once(runner.AUTHORIZATION_TOKEN)

        self.assertEqual(claim_commits, 1)
        self.assertTrue(path_map["claim"].is_file())
        self.assertTrue(path_map["result"].is_file())
        self.assertEqual(value["schema_version"], runner.SCHEMA)
        self.assertIn("UNCAUGHT_POSTCLAIM_EXCEPTION", value["failure_codes"])
        self.assertTrue(value["terminal_contract"]["attempt_consumed"])
        self.assertFalse(value["terminal_contract"]["retry_after_pass_or_fail"])

    def test_preclaim_exception_does_not_forge_terminal_result(self) -> None:
        result = self.root / "preclaim-result.json"
        old_claim_state = runner._CLAIM_CREATED_THIS_PROCESS
        runner._CLAIM_CREATED_THIS_PROCESS = False
        self.addCleanup(setattr, runner, "_CLAIM_CREATED_THIS_PROCESS", old_claim_state)
        with mock.patch.object(runner, "paths", return_value={"result": result}), mock.patch.object(
            runner, "_run_once_impl", side_effect=RuntimeError("synthetic preclaim")
        ):
            with self.assertRaises(RuntimeError):
                runner.run_once("synthetic-token")
        self.assertFalse(result.exists())

    def test_bound_popen_allows_diagnostics_then_only_one_exact_child(self) -> None:
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
        result_dir = self.root / "bound-result"
        result_dir.mkdir()
        path_map = {
            "runtime_config": self.root / "bound-runtime.yaml",
            "result_dir": result_dir,
            "subset_times": self.root / "bound-times.txt",
            "stdout": self.root / "bound.stdout",
            "stderr": self.root / "bound.stderr",
        }
        expected_argv = [
            str(base.BINARY),
            str(path_map["runtime_config"]),
            str(path_map["result_dir"]) + "/",
            str(runner.INPUT_ROOT),
            str(path_map["subset_times"]),
        ]
        environment = {"SYNTHETIC": "1"}
        synthetic_process = mock.Mock(pid=321)
        original = mock.Mock(return_value=synthetic_process)
        adapter._BOUND_POPEN_COUNT = 0
        diagnostic = [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
        with mock.patch.object(adapter, "paths", return_value=path_map), mock.patch.object(
            base, "runtime_environment", return_value=environment
        ), mock.patch.object(supervisor, "_ORIGINAL_POPEN", original):
            self.assertIs(adapter.bound_popen(diagnostic), synthetic_process)
            self.assertEqual(adapter._BOUND_POPEN_COUNT, 0)
            with path_map["stdout"].open("wb") as stdout, path_map["stderr"].open("wb") as stderr:
                with self.assertRaises(base.ContractError):
                    adapter.bound_popen(
                        expected_argv,
                        cwd="wrong",
                        env=environment,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                self.assertIs(
                    adapter.bound_popen(
                        expected_argv,
                        cwd=str(runner.ATTEMPT),
                        env=environment,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    ),
                    synthetic_process,
                )
                with self.assertRaises(base.ContractError):
                    adapter.bound_popen(
                        expected_argv,
                        cwd=str(runner.ATTEMPT),
                        env=environment,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
        self.assertEqual(adapter._BOUND_POPEN_COUNT, 1)

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
