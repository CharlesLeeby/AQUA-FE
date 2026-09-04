from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from scripts import run_p07_backend_b0_materialization_v2 as runtime
from scripts.tests import test_p07_backend_b0_materialization_lock_v2 as lock_tests


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record(path: str, content: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


class B0MaterializationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_class = lock_tests.B0MaterializationLockV2Tests
        fixture_class.setUpClass()
        try:
            fixture = fixture_class(methodName="runTest")
            fixture.setUp()
            cls.formal_payload = fixture.build()
        finally:
            fixture_class.tearDownClass()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / runtime.P07_RELATIVE).mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _legacy_case(self, *, afrl: bool = False):
        window_id = "afrl:bus_outside:0001" if afrl else "aqualoc_harbor:H06:0000"
        source_relative = "inputs/source.bag" if afrl else "inputs/source.tar.gz"
        target_relative = "targets/output.bag"
        reference_relative = "inputs/reference.txt"
        source = b"source-bag" if afrl else b"source-archive"
        output = source if afrl else b"converted-rosbag"
        reference = b"reference"
        (self.root / "inputs").mkdir()
        (self.root / "targets").mkdir()
        (self.root / source_relative).write_bytes(source)
        (self.root / reference_relative).write_bytes(reference)
        template = (
            ["INTERNAL_EXACT_COPY_NOREPLACE", source_relative, "{OUTPUT}"]
            if afrl
            else [
                "python3",
                "-m",
                "uw_frontend.datasets.aqualoc_raw_to_rosbag",
                "--input",
                source_relative,
                "--output-bag",
                "{OUTPUT}",
                "--gt-txt",
                reference_relative,
            ]
        )
        recipe = {
            "window_id": window_id,
            "dataset_family": "afrl" if afrl else "aqualoc_harbor",
            "target_path": target_relative,
            "expected_sha256": hashlib.sha256(output).hexdigest(),
            "expected_size_bytes": len(output),
            "source_raw_path": source_relative,
            "source_raw_sha256": hashlib.sha256(source).hexdigest(),
            "source_path_identity": {
                "resolved_target_identity": {"size_bytes": len(source)}
            },
            "converter_argv_template": template,
            "disposition": (
                "EXACT_COPY_REQUIRED_OR_RECONCILE"
                if afrl
                else "REBUILD_REQUIRED_OR_EXACT_RECONCILE"
            ),
            "camera_topic": "/camera/image_raw",
        }
        entry = {
            "window_id": window_id,
            "dataset_family": recipe["dataset_family"],
            "materialization": {"v1_recipe": recipe},
        }
        lock_payload = {
            runtime.formal_lock.SELF_HASH_FIELD: sha("formal-lock"),
            "b0_core_plan": {"entries": [entry]},
            "legacy_recipe_authority": {
                "input_artifacts": [record(reference_relative, reference)]
            },
        }
        unit = {
            "kind": "LEGACY_EXACT_SINGLE_TARGET",
            "window_ids": [window_id],
        }
        return lock_payload, unit, recipe, output

    @staticmethod
    def _bag_inspector(_path, _recipe):
        return {
            "topic_counts": {"/camera/image_raw": 2},
            "trajectory_values_interpreted": False,
        }

    def test_deterministic_exclusive_nofollow_stage_and_no_name_unlink(self) -> None:
        target = "targets/window.bag"
        (self.root / "targets").mkdir()
        first = runtime.create_retained_stage(
            self.root, target, "window:1", sha("lock")
        )
        try:
            self.assertEqual(
                first.stage_relative,
                runtime.deterministic_stage_relative(target, "window:1", sha("lock")),
            )
            with self.assertRaises(FileExistsError):
                runtime.create_retained_stage(
                    self.root, target, "window:1", sha("lock")
                )
            with mock.patch.object(
                os, "unlink", side_effect=AssertionError("name unlink forbidden")
            ), mock.patch.object(
                Path, "unlink", side_effect=AssertionError("Path.unlink forbidden")
            ):
                preserved = runtime.preserve_stage(first, reason="fixture")
            self.assertEqual(preserved["status"], "PRESERVED")
            self.assertTrue((self.root / preserved["path"]).is_file())
        finally:
            first.close()

    def test_aqualoc_converter_uses_inherited_proc_fds_and_closes_all_fds(self) -> None:
        lock_payload, unit, _recipe, output = self._legacy_case()
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            source_arg = argv[argv.index("--input") + 1]
            output_arg = argv[argv.index("--output-bag") + 1]
            reference_arg = argv[argv.index("--gt-txt") + 1]
            for value in (source_arg, output_arg, reference_arg):
                self.assertRegex(value, r"^/proc/self/fd/[0-9]+$")
                self.assertIn(int(value.rsplit("/", 1)[1]), kwargs["pass_fds"])
            output_fd = int(output_arg.rsplit("/", 1)[1])
            os.ftruncate(output_fd, 0)
            os.pwrite(output_fd, output, 0)
            return SimpleNamespace(returncode=0, stdout=b"converter-log")

        before = len(list(Path("/proc/self/fd").iterdir()))
        with mock.patch.object(
            os, "unlink", side_effect=AssertionError("name unlink forbidden")
        ):
            observation = runtime.materialize_legacy_unit(
                self.root,
                lock_payload,
                unit,
                timeout_s=10,
                bag_inspector=self._bag_inspector,
                subprocess_runner=runner,
            )
        after = len(list(Path("/proc/self/fd").iterdir()))
        self.assertEqual(after, before)
        self.assertEqual(len(calls), 1)
        self.assertEqual(observation["action"], "RENAMED_NOREPLACE")
        self.assertEqual((self.root / observation["target_path"]).read_bytes(), output)
        self.assertFalse(
            (self.root / runtime.deterministic_stage_relative(
                observation["target_path"], observation["window_id"], sha("formal-lock")
            )).exists()
        )

    def test_afrl_is_streamed_from_retained_source_without_subprocess(self) -> None:
        lock_payload, unit, _recipe, output = self._legacy_case(afrl=True)
        with mock.patch.object(
            runtime.subprocess, "run", side_effect=AssertionError("AFRL spawned process")
        ):
            observation = runtime.materialize_legacy_unit(
                self.root,
                lock_payload,
                unit,
                timeout_s=10,
                bag_inspector=self._bag_inspector,
            )
        self.assertEqual(observation["action"], "RENAMED_NOREPLACE")
        self.assertEqual((self.root / observation["target_path"]).read_bytes(), output)

    def test_converter_failure_preserves_stage_and_never_deletes(self) -> None:
        lock_payload, unit, recipe, _output = self._legacy_case()
        with mock.patch.object(
            os, "unlink", side_effect=AssertionError("name unlink forbidden")
        ), mock.patch.object(
            Path, "unlink", side_effect=AssertionError("Path.unlink forbidden")
        ):
            with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
                runtime.materialize_legacy_unit(
                    self.root,
                    lock_payload,
                    unit,
                    timeout_s=10,
                    bag_inspector=self._bag_inspector,
                    subprocess_runner=lambda *_args, **_kwargs: SimpleNamespace(
                        returncode=17, stdout=b"failed"
                    ),
                )
        self.assertEqual(caught.exception.code, "CONVERTER_FAILED")
        preserved = runtime.deterministic_preserved_relative(
            recipe["target_path"], recipe["window_id"], sha("formal-lock")
        )
        self.assertTrue((self.root / preserved).is_file())

    def test_stage_swap_is_detected_from_retained_inode(self) -> None:
        (self.root / "targets").mkdir()
        stage = runtime.create_retained_stage(
            self.root, "targets/final.bag", "window", sha("lock")
        )
        try:
            os.write(stage.descriptor, b"exact")
            original = self.root / stage.stage_relative
            moved = original.with_name(original.name + ".attacker-moved")
            os.rename(original, moved)
            original.write_bytes(b"replacement")
            with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
                runtime.publish_retained_stage(
                    stage,
                    expected_sha256=hashlib.sha256(b"exact").hexdigest(),
                    expected_size=5,
                    root=self.root,
                )
            self.assertEqual(caught.exception.code, "STAGE_PATH_IDENTITY_DRIFT")
        finally:
            stage.close()

    def test_exact_race_winner_is_verified_and_loser_stage_preserved(self) -> None:
        (self.root / "targets").mkdir()
        target = "targets/final.bag"
        content = b"winner"
        (self.root / target).write_bytes(content)
        stage = runtime.create_retained_stage(
            self.root, target, "window", sha("lock")
        )
        try:
            os.write(stage.descriptor, content)
            result = runtime.publish_retained_stage(
                stage,
                expected_sha256=hashlib.sha256(content).hexdigest(),
                expected_size=len(content),
                root=self.root,
            )
            self.assertEqual(result["action"], "EXACT_CONCURRENT_WINNER")
            self.assertTrue((self.root / result["preserved_stage"]["path"]).is_file())
            self.assertEqual((self.root / target).read_bytes(), content)
        finally:
            stage.close()

    def _runtime_sources(self):
        return [
            {"path": "fixture/runtime.py", "sha256": sha("runtime"), "size_bytes": 1}
        ]

    def _fake_observations(self, payload):
        result = []
        for entry in payload["b0_core_plan"]["entries"]:
            digest = entry["target"]["content_sha256"] or sha(entry["window_id"])
            size = entry["target"]["size_bytes"] or 123
            result.append(
                {
                    "window_id": entry["window_id"],
                    "target_path": entry["target"]["path"],
                    "action": "FIXTURE_EXACT",
                    "record": {
                        "path": entry["target"]["path"],
                        "sha256": digest,
                        "size_bytes": size,
                    },
                    "bag_integrity": {"trajectory_values_interpreted": False},
                    "preserved_stage": None,
                    "run_vins": False,
                }
            )
        return result

    def test_durable_intent_precedes_any_stage_and_bundle_closeout_commits_last(self) -> None:
        payload = copy.deepcopy(type(self).formal_payload)
        lock_record = {"path": runtime.FORMAL_LOCK_RELATIVE, "sha256": sha("l"), "size_bytes": 1}
        observations = self._fake_observations(payload)
        by_window = {item["window_id"]: item for item in observations}
        events = []

        def event(kind, path):
            events.append((kind, path))

        def legacy_materializer(root, _payload, unit, **_kwargs):
            self.assertTrue((root / runtime.INTENT_RELATIVE).is_file())
            events.append(("stage", unit["window_ids"][0]))
            return copy.deepcopy(by_window[unit["window_ids"][0]])

        def ntnu_materializer(_root, _payload, _intent):
            values = [
                copy.deepcopy(by_window[item["window_id"]])
                for item in payload["b0_core_plan"]["entries"]
                if item["dataset_family"] == "ntnu"
            ]
            return values, {"fixture": True}, {
                "path": runtime.NTNU_STAGE_RECEIPT_RELATIVE,
                "sha256": sha("stage-receipt"),
                "size_bytes": 1,
            }

        result = runtime.execute_transaction_core(
            payload,
            lock_record,
            started_at="2026-08-08T16:00:00+08:00",
            completed_at="2026-08-08T16:01:00+08:00",
            committed_at="2026-08-08T16:02:00+08:00",
            root=self.root,
            runtime_sources=self._runtime_sources(),
            legacy_materializer=legacy_materializer,
            ntnu_materializer=ntnu_materializer,
            event_hook=event,
        )
        intent_index = events.index(("intent_durable", runtime.INTENT_RELATIVE))
        first_stage = next(index for index, item in enumerate(events) if item[0] == "stage")
        self.assertLess(intent_index, first_stage)
        published = [path for kind, path in events if kind == "published"]
        self.assertEqual(
            published[-4:],
            [
                runtime.RECEIPT_RELATIVE,
                runtime.PLAY_INPUTS_RELATIVE,
                runtime.RESOLVED_ACTUAL_RELATIVE,
                runtime.CLOSEOUT_RELATIVE,
            ],
        )
        self.assertEqual(result["status"], "COMMITTED_LAST_ALL_20_EXACT_MATERIALIZATION_ONLY")
        self.assertFalse(result["run_vins"])
        resolved = json.loads((self.root / runtime.RESOLVED_ACTUAL_RELATIVE).read_text())
        self.assertEqual(resolved["counts"]["unresolved_content_location_count"], 0)
        self.assertEqual(resolved["counts"]["path_location_count"], 202)
        self.assertEqual(resolved["counts"]["cell_count"], 80)
        self.assertEqual(resolved["counts"]["queue_binding_count"], 240)

    def _prepare_ntnu_source(self, payload):
        group = runtime._ntnu_group(payload)
        source = self.root / group["source_path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        content = b"fixture-ntnu-source"
        source.write_bytes(content)
        for item in payload["effective_checksum_records"]:
            if item["path"] == group["source_path"]:
                item["effective_content_sha256"] = hashlib.sha256(content).hexdigest()
                item["size_bytes"] = len(content)
        for target in group["target_paths"]:
            (self.root / target).parent.mkdir(parents=True, exist_ok=True)
        return group

    def _fake_fanout(self, group, calls):
        expected = {item["window_id"]: item for item in group["windows"]}

        def fanout(_source, windows, paths, **_kwargs):
            calls.append([window.window_id for window in windows])
            observations = []
            for window_id, path in paths.items():
                content = ("stage:" + window_id).encode("utf-8")
                Path(path).write_bytes(content)
                contract = expected[window_id]["expected_output"]
                observations.append(
                    {
                        "window_id": window_id,
                        "staged_path": os.fspath(path),
                        "stage_file_identity": runtime._identity(os.stat(path)),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "topic_counts": copy.deepcopy(contract["topic_counts"]),
                        "bag_integrity": {
                            "header_stamp_ranges_ns": {
                                contract["camera_topic"]: copy.deepcopy(
                                    contract["camera_header_evaluation_bounds_ns"]
                                )
                            },
                            "trajectory_values_interpreted": False,
                        },
                    }
                )
            return {
                "reader_traversal_count": 1,
                "final_paths_published": False,
                "ros_or_vins_started": False,
                "held_out_trajectory_outcome_read": False,
                "observations": observations,
            }

        return fanout

    def test_ntnu_receipt_before_rename_crash_and_exact_partial_resume(self) -> None:
        payload = copy.deepcopy(type(self).formal_payload)
        group = self._prepare_ntnu_source(payload)
        intent = {runtime.INTENT_HASH_FIELD: sha("intent")}
        calls = []
        fanout = self._fake_fanout(group, calls)

        def crash(point, _window_id):
            if point == "after_final_rename":
                raise runtime.SimulatedCrash()

        with self.assertRaises(runtime.SimulatedCrash):
            runtime.materialize_ntnu_group(
                self.root,
                payload,
                intent,
                fanout_callable=fanout,
                crash_hook=crash,
            )
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.root / runtime.NTNU_STAGE_RECEIPT_RELATIVE).is_file())
        final_count = sum((self.root / target).is_file() for target in group["target_paths"])
        stage_count = sum(
            (self.root / runtime.deterministic_stage_relative(
                item["target_path"], item["window_id"], payload[runtime.formal_lock.SELF_HASH_FIELD]
            )).is_file()
            for item in group["windows"]
        )
        self.assertEqual((final_count, stage_count), (1, 2))

        resumed, _receipt, _record = runtime.materialize_ntnu_group(
            self.root,
            payload,
            intent,
            fanout_callable=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("fanout reran after receipt")
            ),
        )
        self.assertEqual(len(resumed), 3)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all((self.root / target).is_file() for target in group["target_paths"]))

    def test_ntnu_orphan_stage_without_receipt_and_corrupt_partial_fail_closed(self) -> None:
        payload = copy.deepcopy(type(self).formal_payload)
        group = self._prepare_ntnu_source(payload)
        intent = {runtime.INTENT_HASH_FIELD: sha("intent")}
        first = group["windows"][0]
        orphan = self.root / runtime.deterministic_stage_relative(
            first["target_path"],
            first["window_id"],
            payload[runtime.formal_lock.SELF_HASH_FIELD],
        )
        orphan.write_bytes(b"orphan")
        with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
            runtime.materialize_ntnu_group(
                self.root,
                payload,
                intent,
                fanout_callable=lambda *_args, **_kwargs: {},
            )
        self.assertEqual(caught.exception.code, "ORPHAN_STAGE_WITHOUT_RECEIPT")

        moved = orphan.with_name(orphan.name + ".fixture-moved")
        os.rename(orphan, moved)
        fanout = self._fake_fanout(group, [])
        with self.assertRaises(runtime.SimulatedCrash):
            runtime.materialize_ntnu_group(
                self.root,
                payload,
                intent,
                fanout_callable=fanout,
                crash_hook=lambda point, _window: (
                    (_ for _ in ()).throw(runtime.SimulatedCrash())
                    if point == "after_stage_receipt"
                    else None
                ),
            )
        broken = self.root / runtime.deterministic_stage_relative(
            first["target_path"],
            first["window_id"],
            payload[runtime.formal_lock.SELF_HASH_FIELD],
        )
        os.rename(broken, broken.with_name(broken.name + ".lost"))
        with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
            runtime.materialize_ntnu_group(
                self.root,
                payload,
                intent,
                fanout_callable=lambda *_args, **_kwargs: {},
            )
        self.assertEqual(caught.exception.code, "NTNU_PARTIAL_STATE_NOT_RESUMABLE")

    def test_formal_loader_uses_all_strict_live_flags_then_blocks_unbound_runtime(self) -> None:
        payload = {
            "legacy_recipe_authority": {},
            "formalization_adoption": {},
            "formalization_review_evidence": {},
            "hf_checksum_semantics_correction": {},
            "source_bindings": [
                {"path": path, "sha256": sha(path), "size_bytes": 1}
                for path in runtime.formal_lock.SOURCE_PATHS
            ],
        }
        content = json.dumps(payload).encode("utf-8")
        with mock.patch.object(
            runtime.formal_io, "read_direct_bytes", return_value=(content, {})
        ), mock.patch.object(
            runtime.b0, "load_live_queue_authority", return_value={"queue": True}
        ), mock.patch.object(
            runtime.formal_lock, "validate_lock_payload", return_value=sha("lock")
        ) as validate:
            with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
                runtime.load_and_validate_formal_lock(root=self.root)
        self.assertEqual(caught.exception.code, "RUNTIME_SOURCES_NOT_FORMALLY_BOUND")
        kwargs = validate.call_args.kwargs
        self.assertTrue(kwargs["verify_sources"])
        self.assertTrue(kwargs["verify_live_authorities"])
        self.assertEqual(kwargs["external_legacy_authority"], {})
        self.assertEqual(kwargs["external_source_bindings"], payload["source_bindings"])

    def test_capacity_process_and_run_vins_gates(self) -> None:
        with mock.patch.dict(os.environ, {"RUN_VINS": "1"}):
            with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
                runtime._assert_run_vins_zero()
        self.assertEqual(caught.exception.code, "RUN_VINS_NOT_ZERO")
        with mock.patch.object(
            runtime.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=99),
        ):
            with self.assertRaises(runtime.B0MaterializationV2Error) as caught:
                runtime._check_capacity({"capacity": {"required_free_bytes": 100}}, self.root)
        self.assertEqual(caught.exception.code, "CAPACITY_GATE_FAILED")

    def test_cli_defaults_to_read_only_preflight_and_execute_stays_blocked(self) -> None:
        report = {"status": runtime.STATUS_BLOCKED, "execute_available": False}
        with mock.patch.object(
            runtime, "preflight_report", return_value=report
        ), mock.patch("builtins.print") as printer:
            self.assertEqual(runtime.main([]), 0)
            self.assertEqual(runtime.main(["--preflight"]), 0)
            self.assertEqual(runtime.main(["--execute"]), 2)
        self.assertGreaterEqual(printer.call_count, 3)
        self.assertFalse(runtime.CLI_EXECUTION_IMPLEMENTED)


if __name__ == "__main__":
    unittest.main()
