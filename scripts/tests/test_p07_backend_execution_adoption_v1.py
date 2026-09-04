from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_p07_backend_execution_lock_v1 as builder
from scripts import build_p07_backend_formalization_adoption_v1 as adoption
from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as bridge
from scripts import build_p07_backend_replay_queue_v1 as queue_builder
from scripts.tests import test_p07_backend_execution_lock_v1 as legacy_fixture


class P07BackendExecutionAdoptionV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = legacy_fixture.P07BackendExecutionLockV1Tests(
            "test_lock_binds_serial_order_capacity_and_no_clobber_policy"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.arguments = dict(self.fixture.common)
        self.adoption = {
            "path": adoption.OUTPUT_RELATIVE,
            "sha256": legacy_fixture.digest("formalization-adoption"),
            "size_bytes": 123,
            adoption.SELF_HASH_FIELD: legacy_fixture.digest(
                "formalization-adoption-self"
            ),
        }
        self.prelock = {
            **legacy_fixture.record(
                queue_builder.display_path(builder.B0_ADOPTION_PRELOCK),
                legacy_fixture.digest("b0-adoption-prelock"),
            ),
            bridge.PRELOCK_HASH: legacy_fixture.digest(
                "b0-adoption-prelock-self"
            ),
        }
        self.action_intent = {
            **legacy_fixture.record(
                queue_builder.display_path(builder.B0_ADOPTION_ACTION_INTENT),
                legacy_fixture.digest("b0-adoption-action-intent"),
            ),
            bridge.ACTION_INTENT_HASH: legacy_fixture.digest(
                "b0-adoption-action-intent-self"
            ),
        }
        self.closeout = {
            **legacy_fixture.record(
                queue_builder.display_path(builder.B0_ADOPTION_CLOSEOUT),
                legacy_fixture.digest("b0-adoption-closeout"),
            ),
            bridge.CLOSEOUT_HASH: legacy_fixture.digest(
                "b0-adoption-closeout-self"
            ),
        }
        self.arguments["artifacts"] = [
            *self.arguments["artifacts"],
            legacy_fixture.record(
                adoption.OUTPUT_RELATIVE, self.adoption["sha256"]
            ),
            legacy_fixture.record(
                str(self.prelock["path"]), str(self.prelock["sha256"])
            ),
            legacy_fixture.record(
                str(self.action_intent["path"]),
                str(self.action_intent["sha256"]),
            ),
            legacy_fixture.record(
                str(self.closeout["path"]), str(self.closeout["sha256"])
            ),
        ]
        self.arguments["formalization_adoption"] = self.adoption
        self.evidence = {
            "path": review_evidence.OUTPUT_RELATIVE,
            "sha256": legacy_fixture.digest("formalization-review-evidence"),
            "size_bytes": 123,
            review_evidence.SELF_HASH_FIELD: legacy_fixture.digest(
                "formalization-review-evidence-self"
            ),
        }
        self.arguments["artifacts"].append(
            legacy_fixture.record(
                review_evidence.OUTPUT_RELATIVE, self.evidence["sha256"]
            )
        )
        self.arguments["formalization_review_evidence"] = self.evidence
        self.arguments["b0_adoption_prelock"] = self.prelock
        self.arguments["b0_adoption_action_intent"] = self.action_intent
        self.arguments["b0_adoption_closeout"] = self.closeout
        self.arguments["replacement_contract_binding"] = {
            **self.arguments["replacement_contract_binding"],
            "formalization_adoption": self.adoption,
            "formalization_review_evidence": self.evidence,
        }

    def test_execution_payload_exactly_binds_adoption_and_two_stage_b0_bridge(self) -> None:
        payload = builder.build_lock_payload(**self.arguments)
        self.assertEqual(payload["formalization_adoption"], self.adoption)
        self.assertEqual(
            payload["b0_formalization_adoption"],
            {
                "pre_materialization_lock": self.prelock,
                "materialization_action_intent": self.action_intent,
                "post_materialization_closeout": self.closeout,
            },
        )
        self.assertEqual(payload["formalization_review_evidence"], self.evidence)
        self.assertEqual(
            payload["infrastructure_replacement"]["formalization_adoption"],
            self.adoption,
        )

    def test_delete_substitute_or_rehash_adoption_chain_is_rejected(self) -> None:
        for field in (
            "formalization_adoption",
            "formalization_review_evidence",
            "b0_adoption_prelock",
            "b0_adoption_action_intent",
            "b0_adoption_closeout",
        ):
            arguments = dict(self.arguments)
            arguments[field] = {}
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    builder.ExecutionLockError, "adoption|replacement"
                ):
                    builder.build_lock_payload(**arguments)
        arguments = copy.deepcopy(self.arguments)
        replacement_binding = dict(arguments["replacement_contract_binding"])
        replacement_adoption = dict(
            replacement_binding["formalization_adoption"]
        )
        replacement_adoption[
            adoption.SELF_HASH_FIELD
        ] = "f" * 64
        replacement_binding["formalization_adoption"] = replacement_adoption
        arguments["replacement_contract_binding"] = replacement_binding
        with self.assertRaisesRegex(builder.ExecutionLockError, "replacement"):
            builder.build_lock_payload(**arguments)

    def test_malformed_portable_authority_records_are_rejected(self) -> None:
        for field, member, value in (
            ("formalization_adoption", "sha256", "not-a-sha"),
            ("formalization_adoption", "size_bytes", True),
            ("formalization_review_evidence", "sha256", "not-a-sha"),
            ("b0_adoption_prelock", bridge.PRELOCK_HASH, "0" * 63),
            (
                "b0_adoption_action_intent",
                bridge.ACTION_INTENT_HASH,
                "0" * 63,
            ),
            ("b0_adoption_closeout", "size_bytes", 0),
        ):
            arguments = copy.deepcopy(self.arguments)
            arguments[field][member] = value
            if field in {"formalization_adoption", "formalization_review_evidence"}:
                arguments["replacement_contract_binding"][
                    field
                ] = copy.deepcopy(arguments[field])
            with self.subTest(field=field, member=member):
                expected_error = (
                    "review-evidence"
                    if field == "formalization_review_evidence"
                    else "adoption"
                )
                with self.assertRaisesRegex(
                    builder.ExecutionLockError, expected_error
                ):
                    builder.build_lock_payload(**arguments)

    def test_postlink_guard_failure_rolls_back_only_own_execution_lock_inode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "papers/p07/backend_replay_execution_lock_v1.json"
            output.parent.mkdir(parents=True)
            with mock.patch.object(queue_builder, "ROOT", root), mock.patch.object(
                builder,
                "_revalidate_execution_publication_inputs",
                side_effect=[None, builder.ExecutionLockError("post-link drift")],
            ):
                with self.assertRaisesRegex(
                    builder.ExecutionLockError, "post-link drift"
                ):
                    builder.write_no_clobber(output, {"fixture": True})
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

    def test_postlink_guard_failure_preserves_replacement_race_winner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "papers/p07/backend_replay_execution_lock_v1.json"
            output.parent.mkdir(parents=True)
            calls = 0

            def replace_after_link(_payload: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return
                output.unlink()
                output.write_bytes(b"independent race winner\n")
                raise builder.ExecutionLockError("post-link winner substitution")

            with mock.patch.object(queue_builder, "ROOT", root), mock.patch.object(
                builder,
                "_revalidate_execution_publication_inputs",
                side_effect=replace_after_link,
            ):
                with self.assertRaisesRegex(
                    builder.ExecutionLockError, "winner substitution"
                ):
                    builder.write_no_clobber(output, {"fixture": True})
            self.assertEqual(output.read_bytes(), b"independent race winner\n")
            self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

    def test_destination_replaced_before_postguard_is_never_mistaken_for_own_inode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "papers/p07/backend_replay_execution_lock_v1.json"
            output.parent.mkdir(parents=True)

            def publish_then_steal(
                publish_root: Path,
                relative: str,
                content: bytes,
                **kwargs: object,
            ) -> None:
                destination = publish_root / relative
                temporary = destination.with_name(
                    f".{destination.name}.partial.{os.getpid()}.fixture"
                )
                temporary.write_bytes(content)
                try:
                    kwargs["pre_link_guard"]()
                    os.link(temporary, destination)
                    destination.unlink()
                    destination.write_bytes(b"pre-postguard race winner\n")
                    kwargs["post_link_guard"]()
                finally:
                    temporary.unlink(missing_ok=True)

            with mock.patch.object(queue_builder, "ROOT", root), mock.patch.object(
                builder,
                "_revalidate_execution_publication_inputs",
            ), mock.patch.object(
                queue_builder.formal_io,
                "publish_bytes_no_clobber",
                side_effect=publish_then_steal,
            ):
                with self.assertRaisesRegex(
                    builder.ExecutionLockError, "not the staged inode"
                ):
                    builder.write_no_clobber(output, {"fixture": True})
            self.assertEqual(output.read_bytes(), b"pre-postguard race winner\n")
            self.assertEqual(list(output.parent.glob(".*.partial.*")), [])


if __name__ == "__main__":
    unittest.main()
