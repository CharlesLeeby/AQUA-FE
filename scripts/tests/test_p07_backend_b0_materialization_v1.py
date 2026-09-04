from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import build_p07_backend_b0_materialization_lock_v1 as builder
from scripts import build_p07_backend_replay_queue_v1 as queue_builder
from scripts import p07_backend_replay_common_v1 as common
from scripts import run_p07_backend_b0_materialization_v1 as executor

EPOCH_NS = 1_700_000_000_000_000_000


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class P07BackendB0MaterializationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.sanctioned_patch = mock.patch.dict(
            queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS, {}, clear=True
        )
        self.sanctioned_patch.start()
        self.windows: list[dict[str, str]] = []
        self.rows: list[dict[str, str]] = []
        self.sources: list[dict[str, object]] = []
        self.eligibility: dict[tuple[str, str], dict[str, str]] = {}
        self.checksums: dict[str, str] = {}
        for formal in (
            queue_builder.BACKEND_QUEUE,
            queue_builder.BACKEND_QUEUE_LOCK,
            queue_builder.MANIFEST,
        ):
            path = self.root / formal.relative_to(queue_builder.ROOT)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        queue_index = 0
        for index in range(20):
            family = "afrl" if index == 19 else "ntnu"
            sequence = "bus_outside" if family == "afrl" else f"fixture_{index:02d}"
            window_id = f"{family}:{sequence}:0001"
            start = str(index * 10)
            end = str(index * 10 + 10)
            self.windows.append(
                {
                    "window_id": window_id,
                    "dataset_family": family,
                    "sequence": sequence,
                    "window_start_s": start,
                    "window_end_s": end,
                }
            )
            if family == "ntnu":
                raw = f"datasets/fixtures/{sequence}.bag"
                path = self.root / raw
                path.parent.mkdir(parents=True, exist_ok=True)
                content = f"raw-{sequence}\n".encode()
                path.write_bytes(content)
                self.checksums[raw] = digest(content)
                self.eligibility[(family, sequence)] = {
                    "raw_input_path": raw,
                    "raw_size_bytes": str(len(content)),
                    "reference_path": f"references/{sequence}.txt",
                }
            else:
                self.eligibility[(family, sequence)] = {
                    "raw_input_path": "unused-afrl-raw.bag",
                    "raw_size_bytes": "1",
                    "reference_path": "unused-afrl-reference.txt",
                }
            provenance_hash = digest(window_id.encode())
            for arm in (queue_builder.B0, queue_builder.B1):
                source: dict[str, object] = {
                    "window_id": window_id,
                    "arm": arm,
                    "source_run_id": (
                        f"B0_NATIVE_DATA:{window_id}" if arm == queue_builder.B0 else f"b1-{index}"
                    ),
                    "source_provenance_kind": (
                        "B0_NATIVE_DATA_IDENTITY_V1" if arm == queue_builder.B0 else "FIXTURE"
                    ),
                    "source_provenance_hash": provenance_hash,
                    "source_provenance": {"kind": "FIXTURE"},
                }
                self.sources.append(source)
            for replay in range(1, 4):
                queue_index += 1
                self.rows.append(
                    {
                        "queue_index": str(queue_index),
                        "run_id": f"b0-{index:02d}-{replay}",
                        "window_id": window_id,
                        "dataset_family": family,
                        "sequence": sequence,
                        "runner_start": start,
                        "runner_end_or_duration": "10",
                        "runner_unit": "second",
                        "arm": queue_builder.B0,
                        "source_run_id": f"B0_NATIVE_DATA:{window_id}",
                        "source_provenance_kind": "B0_NATIVE_DATA_IDENTITY_V1",
                        "source_provenance_hash": provenance_hash,
                    }
                )
        self.afrl_source = self.root / (
            "logs/afrl_cave_v31/external_klt_every2_"
            "isj_p07_afrl_bus_outside_0001_b1_attempt01/cave_gennie_short.bag"
        )
        self.afrl_source.parent.mkdir(parents=True)
        self.afrl_source.write_bytes(b"afrl-frozen-short-bag\n")
        attempt = self.root / "papers/afrl-attempt"
        attempt.mkdir(parents=True)
        output_manifest = attempt / "output.sha256"
        source_relative = self.afrl_source.relative_to(self.root).as_posix()
        output_manifest.write_text(
            f"{digest(self.afrl_source.read_bytes())}  {source_relative}\n",
            encoding="utf-8",
        )
        replay_manifest = self.afrl_source.parent / "replay_manifest.txt"
        replay_manifest.write_text("configuration metadata only\n", encoding="utf-8")
        audit = attempt / "audit.json"
        replay_record = self._record(replay_manifest)
        replay_record.update(
            {
                "classification": "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME",
                "vins_csv_absent": True,
                "vins_output_empty": True,
            }
        )
        audit.write_text(
            json.dumps({"afrl_replay_manifest": [replay_record]}), encoding="utf-8"
        )
        afrl_b1 = next(
            item
            for item in self.sources
            if item["window_id"] == "afrl:bus_outside:0001"
            and item["arm"] == queue_builder.B1
        )
        afrl_b1["input_audit_path"] = audit.relative_to(self.root).as_posix()
        afrl_b1["source_provenance"] = {
            "audit": self._record(audit),
            "output_hash_manifest": self._record(output_manifest),
        }
        self.queue_lock = {
            "backend_queue_lock_hash": "a" * 64,
            "source_evidence": self.sources,
        }

    def tearDown(self) -> None:
        self.sanctioned_patch.stop()
        self.tempdir.cleanup()

    def _record(self, path: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": digest(path.read_bytes()),
            "size_bytes": path.stat().st_size,
        }

    @staticmethod
    def _bag_contract(_path: Path, _topic: str) -> dict[str, object]:
        return {
            "topic_counts": {
                "/afrl/colmap_gt": 565,
                "/camera/image_raw": 565,
                "/imu/imu": 4500,
            },
            "camera_stamp_range_ns": {
                "first": EPOCH_NS + 100,
                "last": EPOCH_NS + 200,
            },
            "camera_stamp_source": "sensor_msgs/Image.header.stamp",
            "trajectory_values_interpreted": False,
        }

    @staticmethod
    def _inspect(_path: Path, recipe: dict[str, object]) -> dict[str, object]:
        expected_range = recipe.get("expected_camera_stamp_range_ns")
        return {
            "topic_counts": recipe.get("expected_topic_counts") or {"/cam": 2},
            "camera_topic": recipe["camera_topic"],
            "selected_camera_count": 2,
            "start_ros_time_ns": (
                expected_range["first"]
                if isinstance(expected_range, dict)
                else EPOCH_NS + 100
            ),
            "end_ros_time_ns": (
                expected_range["last"]
                if isinstance(expected_range, dict)
                else EPOCH_NS + 200
            ),
            "selected_record_start_ns": None,
            "selected_record_end_ns": None,
            "stamp_source": "sensor_msgs/Image.header.stamp",
            "trajectory_values_interpreted": False,
        }

    def _plan(self) -> dict[str, object]:
        with mock.patch.object(builder, "_bag_input_contract_bytes", self._bag_contract):
            payload = builder.build_plan_payload(
                frozen_at="2026-08-08T12:00:00+08:00",
                queue_rows=self.rows,
                queue_lock=self.queue_lock,
                manifest_rows=self.windows,
                eligibility_rows=self.eligibility,
                checksums=self.checksums,
                receipts={},
                root=self.root,
                include_code_records=False,
            )
        builder.validate_plan_payload(payload)
        return payload

    def test_governed_json_and_receipt_scan_reject_links(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text(
            json.dumps(
                {
                    "window_id": "ntnu:fixture:0001",
                    "schema_version": "isj-p07-raw-cache-reclamation-v1",
                    "status": "AUTHORIZED_BEFORE_UNLINK",
                    "held_out_trajectory_outcome_read": False,
                    "raw_cache_sha256": "a" * 64,
                    "source_archive_sha256": "b" * 64,
                }
            ),
            encoding="utf-8",
        )
        receipts = self.root / builder.RECEIPT_DIRECTORY.relative_to(builder.ROOT)
        receipts.mkdir(parents=True, exist_ok=True)
        (receipts / "receipt-linked.json").symlink_to(outside)
        with self.assertRaises(builder.B0MaterializationError):
            builder._receipt_by_window(self.root)
        (receipts / "receipt-linked.json").unlink()
        linked = receipts / "receipt-hardlink.json"
        import os

        os.link(outside, linked)
        with self.assertRaises(builder.B0MaterializationError):
            builder._receipt_by_window(self.root)

    def test_streaming_record_freezes_exact_canonical_dataset_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            mounted = base / "mounted"
            wrong = base / "wrong"
            workspace.mkdir()
            (mounted / "inputs").mkdir(parents=True)
            (wrong / "inputs").mkdir(parents=True)
            (mounted / "inputs/source.bin").write_bytes(b"frozen\n")
            (wrong / "inputs/source.bin").write_bytes(b"frozen\n")
            link = workspace / "datasets"
            link.symlink_to(mounted, target_is_directory=True)
            with mock.patch.dict(
                queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS,
                {"datasets": mounted},
                clear=True,
            ):
                record = queue_builder.rooted_io.direct_file_record_bound_input_rooted(
                    workspace,
                    workspace / "datasets/inputs/source.bin",
                    label="synthetic canonical dataset",
                )
                self.assertEqual(record["sha256"], digest(b"frozen\n"))
                link.unlink()
                link.symlink_to(wrong, target_is_directory=True)
                with self.assertRaises(Exception):
                    queue_builder.rooted_io.direct_file_record_bound_input_rooted(
                        workspace,
                        workspace / "datasets/inputs/source.bin",
                        label="synthetic canonical dataset",
                    )

    def test_direct_recipe_rejects_leaf_symlink_and_hardlink(self) -> None:
        window = self.windows[0]
        key = (window["dataset_family"], window["sequence"])
        eligibility = self.eligibility[key]
        original = self.root / eligibility["raw_input_path"]
        content = original.read_bytes()
        original.unlink()
        outside = self.root / "outside.bag"
        outside.write_bytes(content)
        original.symlink_to(outside)
        with self.assertRaises(builder.B0MaterializationError):
            builder._direct_recipe(
                window, eligibility, self.checksums, root=self.root
            )
        original.unlink()
        import os

        os.link(outside, original)
        with self.assertRaises(builder.B0MaterializationError):
            builder._direct_recipe(
                window, eligibility, self.checksums, root=self.root
            )

    def test_sealed_target_inspection_rejects_mid_inspection_path_swap(self) -> None:
        plan = self._plan()
        recipe = next(
            item for item in plan["recipes"] if item["dataset_family"] == "ntnu"
        )
        target = self.root / recipe["target_path"]
        original = target.read_bytes()

        def swap_during_inspection(proc_path: Path, _recipe):
            self.assertTrue(str(proc_path).startswith("/proc/self/fd/"))
            target.unlink()
            target.write_bytes(b"different target bytes\n")
            return self._inspect(proc_path, recipe)

        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "changed during sealed inspection"
        ):
            executor.inspect_exact_target(
                self.root, recipe, bag_inspector=swap_during_inspection
            )
        target.write_bytes(original)

    def test_backend_queue_and_b0_callers_have_no_legacy_path_io(self) -> None:
        forbidden = {
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "open",
            "exists",
            "is_file",
            "is_symlink",
            "glob",
            "stat",
        }
        for relative in (
            "scripts/build_p07_backend_replay_queue_v1.py",
            "scripts/validate_p07_backend_replay_queue_v1.py",
            "scripts/p07_backend_frontend_provenance_v1.py",
            "scripts/build_p07_backend_b0_materialization_lock_v1.py",
            "scripts/run_p07_backend_b0_materialization_v1.py",
            "scripts/register_p07_backend_allocations_v1.py",
            "scripts/build_p07_backend_replacement_contract_v1.py",
            "scripts/build_p07_backend_execution_lock_v1.py",
            "scripts/build_p07_backend_legacy_d_compatibility_lock_v1.py",
        ):
            source = (queue_builder.ROOT / relative).read_text(encoding="utf-8")
            violations: list[tuple[int, str]] = []
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call) or not isinstance(
                    node.func, ast.Attribute
                ):
                    continue
                if node.func.attr not in forbidden:
                    continue
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    continue
                violations.append((node.lineno, node.func.attr))
            self.assertEqual(violations, [], f"{relative} legacy Path I/O")

    def test_plan_has_20_recipes_60_bindings_and_dedicated_afrl_cache(self) -> None:
        payload = self._plan()
        self.assertEqual(len(payload["recipes"]), 20)
        self.assertEqual(len(payload["queue_bindings"]), 60)
        afrl = next(item for item in payload["recipes"] if item["dataset_family"] == "afrl")
        self.assertEqual(
            afrl["target_path"],
            "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag",
        )
        self.assertEqual(afrl["disposition"], "EXACT_COPY_REQUIRED_OR_RECONCILE")
        self.assertEqual(
            afrl["expected_camera_stamp_range_ns"],
            {"first": EPOCH_NS + 100, "last": EPOCH_NS + 200},
        )
        self.assertNotIn("frontend_attempts", afrl["target_path"])

    def test_default_preflight_is_read_only_and_checks_every_source(self) -> None:
        payload = self._plan()
        with mock.patch.object(
            executor,
            "load_frozen_plan",
            return_value=(
                payload,
                {"path": "plan.json", "sha256": "a" * 64, "size_bytes": 1},
            ),
        ), mock.patch.object(
            executor.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=10**12),
        ):
            report = executor.preflight(root=self.root, bag_inspector=self._inspect)
        self.assertEqual(report["exact_existing_target_count"], 19)
        self.assertEqual(report["missing_authorized_target_count"], 1)
        self.assertEqual(report["formal_state"], "PLAN_ONLY")
        self.assertFalse((self.root / builder.INTENT.relative_to(builder.ROOT)).exists())
        self.assertFalse((self.root / builder.RECEIPT.relative_to(builder.ROOT)).exists())
        self.assertFalse((self.root / builder.FINAL_OUTPUT.relative_to(builder.ROOT)).exists())

    def test_a04_recipe_executes_dot_raw_root_and_binds_q55_empty_semantics(self) -> None:
        window_id = "aqualoc_archaeology:A04:0002"
        archive = self.root / "datasets/a04.tar.gz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"archive")
        raw_sha = "b" * 64
        audit = self.root / "papers/a04-audit.json"
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(
            json.dumps(
                {
                    "feature_bag": {
                        "topic_counts": {
                            "/rtimulib_node/imu": 9091,
                            "/aqualoc/colmap_gt": 44,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        for constant in (builder.Q55_LOCK, builder.Q55_CLOSEOUT):
            path = self.root / constant.relative_to(builder.ROOT)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        materialization = self.root / builder.Q55_MATERIALIZATION.relative_to(builder.ROOT)
        materialization.parent.mkdir(parents=True, exist_ok=True)
        counts = {
            "/camera/image_raw": 901,
            "/rtimulib_node/imu": 9091,
            "/aqualoc/colmap_gt": 44,
        }
        materialization.write_text(
            json.dumps({"raw_bag": {"sha256": raw_sha}, "expected_topic_counts": counts}),
            encoding="utf-8",
        )
        recipe = builder._aqualoc_recipe(
            {
                "window_id": window_id,
                "dataset_family": "aqualoc_archaeology",
                "sequence": "A04",
                "window_start_s": "90",
                "window_end_s": "135",
                "input_frame_count": "900",
            },
            {"input_audit_path": audit.relative_to(self.root).as_posix()},
            {
                "raw_input_path": archive.relative_to(self.root).as_posix(),
                "reference_path": "references/a04.txt",
            },
            {archive.relative_to(self.root).as_posix(): digest(archive.read_bytes())},
            {
                window_id: (
                    {
                        "raw_cache_path": "datasets/aqualoc/rosbags/archaeo04_1800_2700.bag",
                        "raw_cache_sha256": raw_sha,
                        "raw_cache_size_bytes": 123,
                        "source_archive_path": archive.relative_to(self.root).as_posix(),
                        "source_archive_sha256": digest(archive.read_bytes()),
                    },
                    {"path": "receipt.json", "sha256": "c" * 64, "size_bytes": 1},
                )
            },
            root=self.root,
        )
        argv = recipe["converter_argv_template"]
        self.assertEqual(argv[argv.index("--raw-root") + 1], ".")
        self.assertEqual(recipe["expected_topic_counts"], counts)
        self.assertEqual(recipe["a04_layout_recovery"]["execution_raw_root_argument"], ".")
        self.assertEqual(recipe["a04_layout_recovery"]["q55_frozen_raw_root_argument"], "")

    def test_afrl_exact_copy_is_no_clobber_and_final_contract_validates(self) -> None:
        plan = self._plan()
        afrl = next(item for item in plan["recipes"] if item["dataset_family"] == "afrl")
        with mock.patch.object(
            executor.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=10**12),
        ):
            observation, _source = executor.materialize_or_reconcile(
                self.root,
                afrl,
                source_cache={},
                timeout_s=10,
                bag_inspector=self._inspect,
                subprocess_runner=mock.Mock(side_effect=AssertionError("no subprocess")),
            )
        target = self.root / afrl["target_path"]
        self.assertEqual(target.read_bytes(), self.afrl_source.read_bytes())
        self.assertEqual(observation["materialization_action"], "MATERIALIZED_AND_LINKED_NOREPLACE")
        self.assertEqual(observation["copy"]["copied_sha256"], afrl["expected_sha256"])
        reconciled, _source = executor.materialize_or_reconcile(
            self.root,
            afrl,
            source_cache={},
            timeout_s=10,
            bag_inspector=self._inspect,
            subprocess_runner=mock.Mock(side_effect=AssertionError("no subprocess")),
        )
        self.assertEqual(reconciled["materialization_action"], "RECONCILED_EXACT_EXISTING")
        target.write_bytes(b"same-path-different-content\n")
        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "hash/size drift"
        ):
            executor.materialize_or_reconcile(
                self.root,
                afrl,
                source_cache={},
                timeout_s=10,
                bag_inspector=self._inspect,
                subprocess_runner=mock.Mock(),
            )
        target.write_bytes(self.afrl_source.read_bytes())

        winner = target.read_bytes()
        temporary = target.parent.resolve() / ".loser.partial"
        temporary.write_bytes(b"loser")
        with self.assertRaises(FileExistsError):
            executor.publish_materialized_target_no_clobber(self.root, temporary, afrl)
        self.assertEqual(target.read_bytes(), winner)
        self.assertTrue(temporary.exists())

        observations = []
        for recipe in plan["recipes"]:
            path = self.root / recipe["target_path"]
            if not path.exists():
                source = self.root / recipe["source_raw_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.read_bytes())
            observations.append(
                {
                    "window_id": recipe["window_id"],
                    "target_path": recipe["target_path"],
                    "sha256": recipe["expected_sha256"],
                    "size_bytes": recipe["expected_size_bytes"],
                    "device": path.stat().st_dev,
                    "inode": path.stat().st_ino,
                    "recipe_hash": recipe["recipe_hash"],
                    "bag_integrity": self._inspect(path, recipe),
                    "held_out_trajectory_outcome_read": False,
                }
            )
        intent = {executor.INTENT_HASH: "f" * 64}
        receipt = executor.build_receipt_payload(
            completed_at="2026-08-08T12:30:00+08:00",
            plan=plan,
            plan_record={"path": "plan.json", "sha256": "d" * 64, "size_bytes": 1},
            intent=intent,
            intent_record={"path": "intent.json", "sha256": "0" * 64, "size_bytes": 1},
            observations=observations,
            source_records=[],
        )
        executor.validate_receipt_payload(receipt, plan, intent)
        attacked_receipt = json.loads(json.dumps(receipt))
        attacked_receipt["observations"][0]["bag_integrity"].update(
            {"start_ros_time_ns": 1, "end_ros_time_ns": 2}
        )
        attacked_receipt[executor.RECEIPT_HASH] = executor.document_hash(
            attacked_receipt, executor.RECEIPT_HASH
        )
        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "target/window drift"
        ):
            executor.validate_receipt_payload(attacked_receipt, plan, intent)
        receipt_record = {
            "path": common.B0_MATERIALIZATION_RECEIPT_PATH,
            "sha256": "e" * 64,
            "size_bytes": 1,
        }
        final = executor.build_b0_play_inputs_payload(
            plan=plan,
            receipt=receipt,
            receipt_record=receipt_record,
            root=self.root,
        )
        common.validate_b0_play_inputs_shape(final, self.rows)
        self.assertEqual(len(final["entries"]), 20)
        self.assertEqual(len(final["queue_bindings"]), 60)

    def test_capacity_failure_occurs_before_converter(self) -> None:
        source = self.root / "datasets/source.tar.gz"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        (self.root / "datasets/aqualoc/rosbags").mkdir(parents=True)
        recipe = {
            "window_id": "aqualoc_harbor:H01:fixture",
            "target_path": "datasets/aqualoc/rosbags/missing.bag",
            "expected_sha256": "f" * 64,
            "expected_size_bytes": 100,
            "source_raw_path": source.relative_to(self.root).as_posix(),
            "source_raw_sha256": digest(source.read_bytes()),
            "source_path_identity": common.capture_canonical_input_identity(
                self.root,
                source.relative_to(self.root).as_posix(),
                expected_sha256=digest(source.read_bytes()),
                verify_sha256=True,
            ),
            "disposition": "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
        }
        runner = mock.Mock()
        with mock.patch.object(
            executor.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=0),
        ), self.assertRaisesRegex(executor.B0MaterializationRuntimeError, "capacity"):
            executor.materialize_or_reconcile(
                self.root,
                recipe,
                source_cache={},
                timeout_s=10,
                bag_inspector=self._inspect,
                subprocess_runner=runner,
            )
        runner.assert_not_called()

    def test_converter_failure_never_publishes_target_or_leaves_stage(self) -> None:
        source = self.root / "datasets/source-failure.tar.gz"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        parent = self.root / "datasets/aqualoc/rosbags"
        parent.mkdir(parents=True)
        target = parent / "failed.bag"
        recipe = {
            "window_id": "aqualoc_harbor:H01:failure",
            "target_path": target.relative_to(self.root).as_posix(),
            "expected_sha256": "f" * 64,
            "expected_size_bytes": 100,
            "source_raw_path": source.relative_to(self.root).as_posix(),
            "source_raw_sha256": digest(source.read_bytes()),
            "source_path_identity": common.capture_canonical_input_identity(
                self.root,
                source.relative_to(self.root).as_posix(),
                expected_sha256=digest(source.read_bytes()),
                verify_sha256=True,
            ),
            "disposition": "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
            "converter_argv_template": [
                "python3",
                "-m",
                "uw_frontend.datasets.aqualoc_raw_to_rosbag",
                "--output-bag",
                "{OUTPUT}",
            ],
        }
        with mock.patch.object(
            executor.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=10**12),
        ), self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "converter failed"
        ):
            executor.materialize_or_reconcile(
                self.root,
                recipe,
                source_cache={},
                timeout_s=10,
                bag_inspector=self._inspect,
                subprocess_runner=mock.Mock(
                    return_value=SimpleNamespace(returncode=9, stdout=b"failed")
                ),
            )
        self.assertFalse(target.exists())
        self.assertEqual(list(parent.glob(".*.partial.*")), [])

    def test_plan_rejects_duplicate_recipe_or_queue_binding(self) -> None:
        payload = self._plan()
        duplicate_recipe = json.loads(json.dumps(payload))
        duplicate_recipe["recipes"][1]["window_id"] = duplicate_recipe["recipes"][0][
            "window_id"
        ]
        duplicate_recipe["recipes"][1]["recipe_hash"] = builder.document_hash(
            duplicate_recipe["recipes"][1], "recipe_hash"
        )
        duplicate_recipe[builder.SELF_HASH] = builder.document_hash(
            duplicate_recipe, builder.SELF_HASH
        )
        with self.assertRaisesRegex(builder.B0MaterializationError, "invalid B0"):
            builder.validate_plan_payload(duplicate_recipe)

        duplicate_binding = json.loads(json.dumps(payload))
        duplicate_binding["queue_bindings"][1] = dict(
            duplicate_binding["queue_bindings"][0]
        )
        duplicate_binding[builder.SELF_HASH] = builder.document_hash(
            duplicate_binding, builder.SELF_HASH
        )
        with self.assertRaisesRegex(builder.B0MaterializationError, "binding"):
            builder.validate_plan_payload(duplicate_binding)

    def test_live_validator_rejects_jointly_rehashed_wrong_window_bag(self) -> None:
        original = self._plan()
        altered = json.loads(json.dumps(original))
        direct = [
            recipe
            for recipe in altered["recipes"]
            if recipe["dataset_family"] == "ntnu"
        ]
        first, second = direct[:2]
        for key in (
            "target_path",
            "expected_sha256",
            "expected_size_bytes",
            "source_raw_path",
            "source_raw_sha256",
            "source_path_identity",
        ):
            first[key] = json.loads(json.dumps(second[key]))
        first["recipe_hash"] = builder.document_hash(first, "recipe_hash")
        altered[builder.SELF_HASH] = builder.document_hash(
            altered, builder.SELF_HASH
        )
        artifact_paths = {str(record["path"]) for record in original["artifacts"]}
        with mock.patch.object(
            builder, "REQUIRED_LIVE_ARTIFACT_PATHS", artifact_paths
        ), mock.patch.object(
            builder, "_assemble_live_payload", return_value=original
        ), self.assertRaisesRegex(
            builder.B0MaterializationError, "deterministic live-input rebuild"
        ):
            builder.validate_plan_payload(
                altered, require_live_artifacts=True, root=self.root
            )

    def test_source_and_hash_bound_code_drift_fail_before_materialization(self) -> None:
        payload = self._plan()
        direct = next(item for item in payload["recipes"] if item["dataset_family"] == "ntnu")
        source = self.root / direct["source_raw_path"]
        source.write_bytes(b"drifted source\n")
        runner = mock.Mock()
        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "source path/link/target drift"
        ):
            executor.materialize_or_reconcile(
                self.root,
                direct,
                source_cache={},
                timeout_s=10,
                bag_inspector=self._inspect,
                subprocess_runner=runner,
            )
        runner.assert_not_called()

        source.write_bytes(f"raw-{direct['sequence']}\n".encode())
        payload = self._plan()
        converter = self.root / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
        converter.parent.mkdir(parents=True)
        converter.write_text("# frozen converter\n", encoding="utf-8")
        payload["artifacts"].append(self._record(converter))
        payload[builder.SELF_HASH] = builder.document_hash(payload, builder.SELF_HASH)
        plan_path = self.root / builder.OUTPUT.relative_to(builder.ROOT)
        queue_builder.formal_io.publish_json_no_clobber(
            self.root, builder.OUTPUT.relative_to(builder.ROOT).as_posix(), payload
        )
        converter.write_bytes(b"converter drift\n")
        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "artifact"
        ):
            executor.load_frozen_plan(root=self.root)
        self.assertTrue(plan_path.is_file())

    def test_failed_converter_leaves_durable_exact_resume_intent_only(self) -> None:
        payload = self._plan()
        plan_record = {"path": "plan.json", "sha256": "a" * 64, "size_bytes": 1}
        failure = executor.B0MaterializationRuntimeError("converter interrupted")
        with mock.patch.object(
            executor, "load_frozen_plan", return_value=(payload, plan_record)
        ), mock.patch.object(
            executor, "materialize_or_reconcile", side_effect=failure
        ):
            with self.assertRaisesRegex(
                executor.B0MaterializationRuntimeError, "interrupted"
            ):
                executor.execute(
                    completed_at="2026-08-08T13:00:00+08:00",
                    timeout_s=10,
                    root=self.root,
                    bag_inspector=self._inspect,
                )
        intent_path = self.root / builder.INTENT.relative_to(builder.ROOT)
        self.assertTrue(intent_path.is_file())
        self.assertFalse((self.root / builder.RECEIPT.relative_to(builder.ROOT)).exists())
        self.assertFalse((self.root / builder.FINAL_OUTPUT.relative_to(builder.ROOT)).exists())
        intent, _record = executor.ensure_durable_intent(
            root=self.root,
            recorded_at="2026-08-08T13:00:00+08:00",
            plan=payload,
            plan_record=plan_record,
        )
        self.assertEqual(intent[executor.INTENT_HASH], executor.document_hash(intent, executor.INTENT_HASH))
        intent_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(
            executor.B0MaterializationRuntimeError, "not exact"
        ):
            executor.ensure_durable_intent(
                root=self.root,
                recorded_at="2026-08-08T13:00:00+08:00",
                plan=payload,
                plan_record=plan_record,
            )

    def test_rosbag_topic_stamp_and_ntnu_absolute_window_contracts(self) -> None:
        class Stamp:
            def __init__(self, value: int) -> None:
                self.value = value

            def to_nsec(self) -> int:
                return self.value

        class Message:
            def __init__(self, value: int) -> None:
                self.header = SimpleNamespace(stamp=Stamp(value))

        class Topic:
            def __init__(self, count: int) -> None:
                self.message_count = count

        class Bag:
            records = [
                ("/cam", Message(EPOCH_NS + 5), Stamp(1_500_000_000)),
                ("/cam", Message(EPOCH_NS + 10), Stamp(2_100_000_000)),
                ("/cam", Message(EPOCH_NS + 20), Stamp(2_900_000_000)),
                ("/cam", Message(EPOCH_NS + 30), Stamp(3_100_000_000)),
            ]

            def __init__(self, _path: str, _mode: str) -> None:
                pass

            def __enter__(self) -> "Bag":
                return self

            def __exit__(self, *_args: object) -> None:
                pass

            def get_start_time(self) -> float:
                return 1.0

            def get_type_and_topic_info(self) -> SimpleNamespace:
                return SimpleNamespace(topics={"/cam": Topic(4), "/imu": Topic(9)})

            def read_messages(self, topics: list[str]):
                return (item for item in self.records if item[0] in topics)

        path = self.root / "fixture.bag"
        path.write_bytes(b"bag")
        base = {
            "window_id": "ntnu:fixture:0001",
            "camera_topic": "/cam",
            "disposition": "DIRECT_RAW_WINDOW_PLAYBACK",
            "runner_start": "1",
            "runner_end_or_duration": "1",
            "expected_topic_counts": None,
        }
        with mock.patch.dict(sys.modules, {"rosbag": SimpleNamespace(Bag=Bag)}):
            with executor._sealed_bag_snapshot(path.read_bytes()) as procfd_path:
                observed = executor.inspect_rosbag(procfd_path, base)
                self.assertEqual(observed["start_ros_time_ns"], EPOCH_NS + 10)
                self.assertEqual(observed["end_ros_time_ns"], EPOCH_NS + 20)
                self.assertEqual(observed["selected_record_start_ns"], 2_000_000_000)
                self.assertEqual(observed["selected_record_end_ns"], 3_000_000_000)
                sealed_observed = executor.inspect_rosbag(procfd_path, base)
                self.assertEqual(
                    sealed_observed["start_ros_time_ns"], EPOCH_NS + 10
                )
                with self.assertRaisesRegex(
                    executor.B0MaterializationRuntimeError, "topic-count"
                ):
                    executor.inspect_rosbag(
                        procfd_path, {**base, "expected_topic_counts": {"/cam": 3}}
                    )
                with self.assertRaisesRegex(
                    executor.B0MaterializationRuntimeError, "stamp-range"
                ):
                    executor.inspect_rosbag(
                        procfd_path,
                        {
                            **base,
                            "expected_camera_stamp_range_ns": {
                                "first": EPOCH_NS + 9,
                                "last": EPOCH_NS + 20,
                            },
                        },
                    )

    def test_canonical_ntnu_link_target_and_formal_symlinks_fail_closed(self) -> None:
        mounted = self.root / "mounted"
        mounted.mkdir()
        first = mounted / "first.bag"
        second = mounted / "second.bag"
        first.write_bytes(b"same bytes\n")
        second.write_bytes(b"same bytes\n")
        canonical = self.root / "canonical"
        canonical.symlink_to(mounted, target_is_directory=True)
        final_link = mounted / "selected.bag"
        final_link.symlink_to("first.bag")
        identity = common.capture_canonical_input_identity(
            self.root,
            "canonical/selected.bag",
            expected_sha256=digest(first.read_bytes()),
            verify_sha256=True,
        )
        final_link.unlink()
        final_link.symlink_to("second.bag")
        with self.assertRaises(common.BackendReplayViolation):
            common.revalidate_canonical_input_identity(
                self.root, identity, verify_sha256=False
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside-plan.json"
            outside.write_text("{}", encoding="utf-8")
            plan_path = root / builder.OUTPUT.relative_to(builder.ROOT)
            plan_path.parent.mkdir(parents=True)
            plan_path.symlink_to(outside)
            with self.assertRaises(Exception):
                executor.load_frozen_plan(root=root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workspace"
            outside = Path(temporary) / "outside"
            outside_plan = outside / builder.OUTPUT.relative_to(builder.ROOT)
            outside_plan.parent.mkdir(parents=True)
            outside_plan.write_text("{}", encoding="utf-8")
            root.mkdir()
            (root / "papers").symlink_to(outside / "papers", target_is_directory=True)
            with self.assertRaises(Exception):
                executor.load_frozen_plan(root=root)

    def test_dangling_receipt_symlink_blocks_before_closeout(self) -> None:
        payload = self._plan()
        receipt = self.root / builder.RECEIPT.relative_to(builder.ROOT)
        receipt.symlink_to(self.root / "missing-receipt-target")
        with mock.patch.object(
            executor,
            "load_frozen_plan",
            return_value=(
                payload,
                {"path": "plan.json", "sha256": "a" * 64, "size_bytes": 1},
            ),
        ):
            with self.assertRaises(Exception):
                executor.execute(
                    completed_at="2026-08-08T14:00:00+08:00",
                    timeout_s=10,
                    root=self.root,
                    bag_inspector=self._inspect,
                )
        self.assertFalse((self.root / builder.FINAL_OUTPUT.relative_to(builder.ROOT)).exists())


if __name__ == "__main__":
    unittest.main()
