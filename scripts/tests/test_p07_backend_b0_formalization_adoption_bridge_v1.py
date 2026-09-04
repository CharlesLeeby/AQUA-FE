from __future__ import annotations

import contextlib
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as bridge
from scripts import run_p07_backend_b0_materialization_adopted_v1 as adopted_runtime


def record(path: str, token: str = "a") -> dict[str, object]:
    return {"path": path, "sha256": token * 64, "size_bytes": 1}


def timed(path: str, token: str, when: int) -> dict[str, object]:
    return {
        **record(path, token),
        "device": 1,
        "inode": when,
        "nlink": 1,
        "mtime_ns": when,
        "ctime_ns": when + 1,
    }


class P07BackendB0FormalizationAdoptionBridgeV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.adoption = {
            "path": bridge.adoption.OUTPUT_RELATIVE,
            "sha256": "1" * 64,
            "size_bytes": 10,
            bridge.adoption.SELF_HASH_FIELD: "2" * 64,
        }
        self.review = {
            "path": bridge.review_evidence.OUTPUT_RELATIVE,
            "sha256": "3" * 64,
            "size_bytes": 11,
            bridge.review_evidence.SELF_HASH_FIELD: "4" * 64,
        }
        self.plan_record = record(
            bridge._relative(bridge.b0_plan.OUTPUT, root=bridge.ROOT), "5"
        )
        self.sources = [
            record(path, format(index % 16, "x"))
            for index, path in enumerate(bridge.REQUIRED_SOURCE_PATHS, start=6)
        ]
        self.formal_absence = [
            {
                "path": path,
                "lexical_state": "ABSENT",
                "parent_state": "DIRECTORY",
                "parent_device": 1,
                "parent_inode": 2,
                "matching_partial_or_staging_entries": [],
            }
            for path in bridge.FORMAL_ABSENCE_PATHS
        ]
        self.cache_absence = [
            {
                "window_id": "family:sequence:0001",
                "target_path": "datasets/cache/window.bag",
                "expected_sha256": "6" * 64,
                "expected_size_bytes": 10,
                "recipe_hash": "7" * 64,
                "namespace": {
                    "path": "datasets/cache/window.bag",
                    "lexical_state": "ABSENT",
                    "parent_state": "DIRECTORY",
                    "parent_device": 1,
                    "parent_inode": 3,
                    "matching_partial_or_staging_entries": [],
                },
            }
        ]
        self.quiet = {
            "protocol": bridge.RELATED_PROCESS_PROTOCOL,
            "matching_process_count": 0,
            "no_related_process_active": True,
        }
        self.prelock = bridge.build_prelock_payload(
            frozen_at="2026-08-08T14:00:00+08:00",
            adoption_binding=self.adoption,
            review_evidence_binding=self.review,
            plan_record=self.plan_record,
            plan_hash="8" * 64,
            source_artifacts=self.sources,
            cache_namespace_pre_state=self.cache_absence,
            formal_output_pre_state=self.formal_absence,
            process_quiescence=self.quiet,
        )

    def minimal_plan(self) -> dict[str, object]:
        return {
            "recipes": [
                {
                    "window_id": "family:sequence:0001",
                    "target_path": "datasets/cache/window.bag",
                    "expected_sha256": "6" * 64,
                    "expected_size_bytes": 10,
                    "recipe_hash": "7" * 64,
                    "source_raw_path": "datasets/raw/source",
                    "source_raw_sha256": "9" * 64,
                    "disposition": "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
                }
            ]
        }

    def make_root(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "papers/ieee_sensors_journal_experiments/p07").mkdir(parents=True)
        (root / "datasets/cache").mkdir(parents=True)
        return temporary

    def test_prelock_binds_both_authorities_and_exact_absence(self) -> None:
        self.assertEqual(
            bridge.validate_prelock_payload(self.prelock, verify_files=False),
            self.prelock[bridge.PRELOCK_HASH],
        )
        self.assertEqual(self.prelock["formalization_review_evidence"], self.review)
        self.assertFalse(self.prelock["authorization"]["backend_replay_authorized"])
        for field in ("formalization_adoption", "formalization_review_evidence"):
            changed = copy.deepcopy(self.prelock)
            changed[field]["path"] = "papers/evil.json"
            changed[bridge.PRELOCK_HASH] = bridge._hash(changed, bridge.PRELOCK_HASH)
            with self.subTest(field=field):
                with self.assertRaises(bridge.B0AdoptionBridgeError):
                    bridge.validate_prelock_payload(changed, verify_files=False)

    def test_action_intent_binds_exact_argv_plan_sources_and_prelock(self) -> None:
        argv = bridge.canonical_wrapper_argv(
            action_started_at="2026-08-08T14:01:00+08:00",
            completed_at="2026-08-08T14:02:00+08:00",
            closed_at="2026-08-08T14:03:00+08:00",
            timeout_s=9,
        )
        payload = bridge.build_action_intent_payload(
            recorded_at="2026-08-08T14:01:00+08:00",
            completed_at="2026-08-08T14:02:00+08:00",
            closed_at="2026-08-08T14:03:00+08:00",
            timeout_s=9,
            adoption_binding=self.adoption,
            review_evidence_binding=self.review,
            prelock_record=record(bridge._relative(bridge.PRELOCK, root=bridge.ROOT), "a"),
            prelock_hash=str(self.prelock[bridge.PRELOCK_HASH]),
            plan_record=self.plan_record,
            plan_hash="8" * 64,
            wrapper_argv=argv,
            plan_sources=bridge.plan_source_hashes(self.minimal_plan()),
            source_artifacts=self.sources,
            cache_namespace_pre_state=self.cache_absence,
            formal_output_pre_state=self.formal_absence,
            process_quiescence=self.quiet,
        )
        self.assertEqual(
            bridge.validate_action_intent_payload(payload, verify_files=False),
            payload[bridge.ACTION_INTENT_HASH],
        )
        changed = copy.deepcopy(payload)
        changed["wrapper_argv"][-1] = "10"
        changed[bridge.ACTION_INTENT_HASH] = bridge._hash(
            changed, bridge.ACTION_INTENT_HASH
        )
        with self.assertRaises(bridge.B0AdoptionBridgeError):
            bridge.validate_action_intent_payload(changed, verify_files=False)

    def test_old_runner_first_then_late_prelock_is_rejected(self) -> None:
        with self.make_root() as directory:
            root = Path(directory)
            target = root / "datasets/cache/window.bag"
            target.write_bytes(b"old-runner-output")
            with self.assertRaisesRegex(
                bridge.B0AdoptionBridgeError, "cache namespace is not pristine"
            ):
                bridge.capture_cache_namespace_absence(self.minimal_plan(), root=root)

    def test_prelock_then_direct_old_runner_without_action_is_rejected(self) -> None:
        with self.make_root() as directory:
            root = Path(directory)
            bridge.capture_cache_namespace_absence(self.minimal_plan(), root=root)
            bridge.capture_formal_output_absence(root=root)
            old_intent = root / bridge._relative(bridge.b0_plan.INTENT, root=bridge.ROOT)
            old_intent.write_text("direct old runner", encoding="utf-8")
            with self.assertRaisesRegex(
                bridge.B0AdoptionBridgeError, "formal output already exists"
            ):
                bridge.capture_formal_output_absence(root=root)

    def test_symlink_and_partial_namespace_are_lexically_rejected(self) -> None:
        with self.make_root() as directory:
            root = Path(directory)
            target = root / "datasets/cache/window.bag"
            target.symlink_to("missing")
            with self.assertRaises(bridge.B0AdoptionBridgeError):
                bridge.capture_cache_namespace_absence(self.minimal_plan(), root=root)
            target.unlink()
            (target.parent / ".window.bag.partial.attacker").write_bytes(b"x")
            with self.assertRaises(bridge.B0AdoptionBridgeError):
                bridge.capture_cache_namespace_absence(self.minimal_plan(), root=root)
            action = root / bridge._relative(bridge.ACTION_INTENT, root=bridge.ROOT)
            action.symlink_to("missing")
            with self.assertRaises(bridge.B0AdoptionBridgeError):
                bridge.capture_formal_output_absence(root=root)

    def test_no_clobber_collision_and_race_preserve_attacker_and_clean_stage(self) -> None:
        with self.make_root() as directory:
            root = Path(directory)
            relative = bridge._relative(bridge.ACTION_INTENT, root=bridge.ROOT)
            destination = root / relative
            token = bridge._LOCKS_HELD.set(True)
            try:
                destination.symlink_to("attacker")
                with self.assertRaises(FileExistsError):
                    bridge._publish_json_locked(
                        root=root,
                        relative=relative,
                        payload={"x": 1},
                        pre_guard=lambda: None,
                        post_guard=lambda: None,
                    )
                self.assertTrue(destination.is_symlink())
                destination.unlink()

                def steal_destination() -> None:
                    destination.unlink()
                    destination.write_bytes(b"attacker-winner")

                with self.assertRaises(bridge.B0AdoptionBridgeError):
                    bridge._publish_json_locked(
                        root=root,
                        relative=relative,
                        payload={"x": 2},
                        pre_guard=lambda: None,
                        post_guard=lambda: None,
                        post_link_hook=steal_destination,
                    )
                self.assertEqual(destination.read_bytes(), b"attacker-winner")
                self.assertEqual(
                    list(destination.parent.glob(f".{destination.name}.partial.*")), []
                )
            finally:
                bridge._LOCKS_HELD.reset(token)

    def test_crash_after_action_never_calls_closeout_or_second_executor(self) -> None:
        argv = bridge.canonical_wrapper_argv(
            action_started_at="2026-08-08T14:01:00+08:00",
            completed_at="2026-08-08T14:02:00+08:00",
            closed_at="2026-08-08T14:03:00+08:00",
            timeout_s=9,
        )
        action = {"action": "durable"}
        boom = mock.Mock(side_effect=RuntimeError("synthetic crash"))
        with mock.patch.object(
            adopted_runtime.bridge, "governance_locks", return_value=contextlib.nullcontext()
        ), mock.patch.object(
            adopted_runtime.bridge, "load_prelock", return_value=({}, {})
        ), mock.patch.object(
            adopted_runtime.bridge, "build_live_action_intent", return_value=action
        ), mock.patch.object(
            adopted_runtime.bridge, "publish_action_intent_locked"
        ) as publish_action, mock.patch.object(
            adopted_runtime.bridge, "load_action_intent", return_value=(action, {})
        ), mock.patch.object(
            adopted_runtime.bridge, "wait_past_action_filesystem_time"
        ), mock.patch.object(
            adopted_runtime.bridge,
            "reuse_held_locks_for_frozen_runtime",
            return_value=contextlib.nullcontext(),
        ), mock.patch.object(
            adopted_runtime.bridge, "publish_closeout_locked"
        ) as publish_closeout:
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                adopted_runtime.execute(
                    action_started_at="2026-08-08T14:01:00+08:00",
                    completed_at="2026-08-08T14:02:00+08:00",
                    closed_at="2026-08-08T14:03:00+08:00",
                    timeout_s=9,
                    action_argv=argv,
                    root=Path("/synthetic"),
                    frozen_execute=boom,
                )
        publish_action.assert_called_once()
        boom.assert_called_once()
        publish_closeout.assert_not_called()

    def test_closeout_requires_strict_filesystem_order_and_noreplace_cache(self) -> None:
        cache = {
            **timed("datasets/cache/window.bag", "6", 40),
            "window_id": "family:sequence:0001",
            "recipe_hash": "7" * 64,
            "materialization_action": "MATERIALIZED_AND_LINKED_NOREPLACE",
            "topic_counts": {"/camera": 10},
            "camera_topic": "/camera",
            "matching_partial_or_staging_entries": [],
        }
        order = {
            "policy": "PRELOCK_LT_ACTION_LT_V1_INTENT_LE_EACH_CACHE_LE_RECEIPT_LE_FINAL_BY_MTIME_AND_CTIME_NS_WITH_HASH_INODE_CONTENT_CHAIN",
            "formal_artifacts": {
                "pre_materialization_lock": timed(bridge._relative(bridge.PRELOCK, root=bridge.ROOT), "a", 10),
                "materialization_action_intent": timed(bridge._relative(bridge.ACTION_INTENT, root=bridge.ROOT), "b", 20),
                "b0_materialization_intent": timed(bridge._relative(bridge.b0_plan.INTENT, root=bridge.ROOT), "c", 30),
                "b0_materialization_receipt": timed(bridge._relative(bridge.b0_plan.RECEIPT, root=bridge.ROOT), "d", 50),
                "b0_play_inputs": timed(bridge._relative(bridge.b0_plan.FINAL_OUTPUT, root=bridge.ROOT), "e", 60),
            },
        }
        payload = bridge.build_closeout_payload(
            closed_at="2026-08-08T14:04:00+08:00",
            adoption_binding=self.adoption,
            review_evidence_binding=self.review,
            prelock_record=record(bridge._relative(bridge.PRELOCK, root=bridge.ROOT), "a"),
            prelock_hash=str(self.prelock[bridge.PRELOCK_HASH]),
            action_intent_record=record(bridge._relative(bridge.ACTION_INTENT, root=bridge.ROOT), "b"),
            action_intent_hash="b" * 64,
            plan_record=self.plan_record,
            plan_hash="8" * 64,
            intent_record=record(bridge._relative(bridge.b0_plan.INTENT, root=bridge.ROOT), "c"),
            intent_hash="c" * 64,
            receipt_record=record(bridge._relative(bridge.b0_plan.RECEIPT, root=bridge.ROOT), "d"),
            receipt_hash="d" * 64,
            final_record=record(bridge._relative(bridge.b0_plan.FINAL_OUTPUT, root=bridge.ROOT), "e"),
            final_hash="e" * 64,
            cache_finalization=[cache],
            artifact_time_order=order,
            process_quiescence=self.quiet,
        )
        self.assertEqual(
            bridge.validate_closeout_payload(payload, verify_files=False),
            payload[bridge.CLOSEOUT_HASH],
        )
        changed = copy.deepcopy(payload)
        changed["artifact_time_order"]["formal_artifacts"]["b0_materialization_receipt"]["mtime_ns"] = 35
        changed[bridge.CLOSEOUT_HASH] = bridge._hash(changed, bridge.CLOSEOUT_HASH)
        with self.assertRaises(bridge.B0AdoptionBridgeError):
            bridge.validate_closeout_payload(changed, verify_files=False)

    def test_post_intent_filesystem_ties_are_allowed_but_reversal_is_rejected(self) -> None:
        cache = {
            **timed("datasets/cache/window.bag", "6", 40),
            "window_id": "family:sequence:0001",
            "recipe_hash": "7" * 64,
            "materialization_action": "MATERIALIZED_AND_LINKED_NOREPLACE",
            "topic_counts": {"/camera": 10},
            "camera_topic": "/camera",
            "matching_partial_or_staging_entries": [],
        }
        order = {
            "policy": "PRELOCK_LT_ACTION_LT_V1_INTENT_LE_EACH_CACHE_LE_RECEIPT_LE_FINAL_BY_MTIME_AND_CTIME_NS_WITH_HASH_INODE_CONTENT_CHAIN",
            "formal_artifacts": {
                "pre_materialization_lock": timed(
                    bridge._relative(bridge.PRELOCK, root=bridge.ROOT), "a", 10
                ),
                "materialization_action_intent": timed(
                    bridge._relative(bridge.ACTION_INTENT, root=bridge.ROOT), "b", 20
                ),
                "b0_materialization_intent": timed(
                    bridge._relative(bridge.b0_plan.INTENT, root=bridge.ROOT), "c", 40
                ),
                "b0_materialization_receipt": timed(
                    bridge._relative(bridge.b0_plan.RECEIPT, root=bridge.ROOT), "d", 40
                ),
                "b0_play_inputs": timed(
                    bridge._relative(bridge.b0_plan.FINAL_OUTPUT, root=bridge.ROOT), "e", 40
                ),
            },
        }
        bridge.validate_artifact_time_order(order, [cache])
        reversed_order = copy.deepcopy(order)
        reversed_order["formal_artifacts"]["b0_materialization_receipt"][
            "ctime_ns"
        ] = 39
        with self.assertRaises(bridge.B0AdoptionBridgeError):
            bridge.validate_artifact_time_order(reversed_order, [cache])


if __name__ == "__main__":
    unittest.main()
