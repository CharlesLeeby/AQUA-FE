from __future__ import annotations

import copy
import hashlib
import unittest
from unittest import mock

from scripts import build_p07_backend_b0_materialization_lock_v2 as lock
from scripts import build_p07_backend_formalization_adoption_v1 as adoption
from scripts import build_p07_backend_formalization_review_evidence_v1 as review
from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as hf
from scripts import p07_backend_b0_legacy_recipe_authority_v1 as legacy
from scripts.tests import test_p07_backend_b0_legacy_recipe_authority_v1 as legacy_tests
from scripts.tests import test_p07_backend_b0_plan_v2 as b0_tests


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class B0MaterializationLockV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_class = legacy_tests.LegacyRecipeAuthorityV1Tests
        fixture_class.setUpClass()
        try:
            legacy_fixture = fixture_class(methodName="runTest")
            legacy_fixture.setUp()
            cls.legacy_payload = legacy_fixture.build()
        finally:
            fixture_class.tearDownClass()

    def setUp(self) -> None:
        fixture = b0_tests.P07BackendB0PlanV2Tests(methodName="runTest")
        fixture.setUp()
        self.queue = fixture.queue_authority
        self.effective = copy.deepcopy(fixture.effective)
        self.adoption = {
            "path": adoption.OUTPUT_RELATIVE,
            "sha256": sha("adoption-file"),
            "size_bytes": 100,
            adoption.SELF_HASH_FIELD: sha("adoption-self"),
        }
        self.review = {
            "path": review.OUTPUT_RELATIVE,
            "sha256": sha("review-file"),
            "size_bytes": 101,
            review.SELF_HASH_FIELD: sha("review-self"),
        }
        self.hf = {
            "path": lock.resolver.CORRECTION_LOCK_RELATIVE,
            "sha256": sha("hf-file"),
            "size_bytes": 102,
            hf.SELF_HASH_FIELD: sha("hf-self"),
        }
        self.sources = [
            {"path": path, "sha256": sha(path), "size_bytes": len(path)}
            for path in sorted(lock.SOURCE_PATHS)
        ]
        provisional = lock.b0.build_core_plan(
            frozen_windows=list(lock.b0.FROZEN_WINDOWS.values()),
            validated_v1_plan_or_recipes=self.legacy_payload,
            effective_checksum_records=self.effective,
            frozen_queue_authority=self.queue,
        )
        self.observations = {
            str(entry["target"]["path"]): None for entry in provisional["entries"]
        }

    def build(self, **overrides):
        return lock.build_lock_payload(
            frozen_at="2026-08-08T15:30:00+08:00",
            legacy_authority=overrides.get("legacy", self.legacy_payload),
            effective_checksum_records=overrides.get("effective", self.effective),
            frozen_queue_authority=self.queue,
            adoption_binding=overrides.get("adoption", self.adoption),
            review_evidence_binding=overrides.get("review", self.review),
            hf_correction_binding=overrides.get("hf", self.hf),
            source_bindings=overrides.get("sources", self.sources),
            target_observations=overrides.get("observations", self.observations),
        )

    def validate(self, payload):
        return lock.validate_lock_payload(
            payload,
            frozen_queue_authority=self.queue,
            external_legacy_authority=self.legacy_payload,
            external_adoption_binding=self.adoption,
            external_review_evidence_binding=self.review,
            external_hf_correction_binding=self.hf,
            external_source_bindings=self.sources,
        )

    def test_exact_lock_is_nonexecution_authority(self) -> None:
        payload = self.build()
        self.assertEqual(self.validate(payload), payload[lock.SELF_HASH_FIELD])
        self.assertEqual(payload["counts"]["window_count"], 20)
        self.assertEqual(payload["counts"]["materialization_unit_count"], 18)
        self.assertEqual(len(payload["materialization_units"]), 18)
        self.assertEqual(
            len(payload["actual_consumed_pre_materialization_core"]["cells"]), 80
        )
        self.assertEqual(
            len(payload["actual_consumed_pre_materialization_core"]["queue_bindings"]),
            240,
        )
        self.assertFalse(payload["policy"]["run_vins"])
        self.assertFalse(payload["policy"]["backend_replay_authorized"])
        self.assertEqual(
            payload["capacity"]["ntnu_unresolved_window_count"], 3
        )

    def test_rehashed_nested_authority_and_core_tampering_is_rejected(self) -> None:
        base = self.build()
        mutations = []
        value = copy.deepcopy(base)
        value["formalization_adoption"]["sha256"] = sha("attacker")
        mutations.append(value)
        value = copy.deepcopy(base)
        value["legacy_recipe_authority"]["policy"]["vins_execution_authorized"] = True
        value["legacy_recipe_authority"][legacy.SELF_HASH_FIELD] = legacy.document_hash(
            value["legacy_recipe_authority"], legacy.SELF_HASH_FIELD
        )
        mutations.append(value)
        value = copy.deepcopy(base)
        value["effective_checksum_records"][0]["effective_content_sha256"] = "0" * 64
        mutations.append(value)
        value = copy.deepcopy(base)
        value["b0_core_plan"]["entries"][0]["target"]["path"] = "datasets/attacker.bag"
        value["b0_core_plan"]["entries"][0]["entry_hash"] = lock.b0.document_hash(
            value["b0_core_plan"]["entries"][0], "entry_hash"
        )
        value["b0_core_plan"][lock.b0.SELF_HASH_FIELD] = lock.b0.document_hash(
            value["b0_core_plan"], lock.b0.SELF_HASH_FIELD
        )
        mutations.append(value)
        value = copy.deepcopy(base)
        value["actual_consumed_pre_materialization_core"]["policy"][
            "execution_authorized"
        ] = True
        value["actual_consumed_pre_materialization_core"][
            lock.actual.SELF_HASH_FIELD
        ] = lock.actual.document_hash(
            value["actual_consumed_pre_materialization_core"],
            lock.actual.SELF_HASH_FIELD,
        )
        mutations.append(value)
        for candidate in mutations:
            candidate[lock.SELF_HASH_FIELD] = lock.document_hash(
                candidate, lock.SELF_HASH_FIELD
            )
            with self.subTest(keys=list(candidate)):
                with self.assertRaises(Exception):
                    self.validate(candidate)

    def test_unit_capacity_target_and_source_closure_tampering_is_rejected(self) -> None:
        base = self.build()
        variants = []
        value = copy.deepcopy(base)
        value["materialization_units"][0]["publication"] = "OVERWRITE"
        variants.append(value)
        value = copy.deepcopy(base)
        value["capacity"]["required_free_bytes"] -= 1
        variants.append(value)
        value = copy.deepcopy(base)
        value["pre_freeze_target_states"][0]["state"] = "EXACT_EXISTING"
        variants.append(value)
        value = copy.deepcopy(base)
        value["source_bindings"][0]["sha256"] = sha("changed source")
        variants.append(value)
        value = copy.deepcopy(base)
        value["source_bindings"].append(
            {"path": "scripts/attacker.py", "sha256": sha("x"), "size_bytes": 1}
        )
        variants.append(value)
        for candidate in variants:
            candidate[lock.SELF_HASH_FIELD] = lock.document_hash(
                candidate, lock.SELF_HASH_FIELD
            )
            with self.assertRaises(Exception):
                self.validate(candidate)

    def test_ntnu_collision_is_rejected_and_exact_legacy_target_is_allowed(self) -> None:
        core = lock.b0.build_core_plan(
            frozen_windows=list(lock.b0.FROZEN_WINDOWS.values()),
            validated_v1_plan_or_recipes=self.legacy_payload,
            effective_checksum_records=self.effective,
            frozen_queue_authority=self.queue,
        )
        ntnu = next(item for item in core["entries"] if item["dataset_family"] == "ntnu")
        collision = copy.deepcopy(self.observations)
        collision[ntnu["target"]["path"]] = {
            "path": ntnu["target"]["path"],
            "sha256": sha("unbound ntnu"),
            "size_bytes": 1,
        }
        with self.assertRaises(lock.B0MaterializationLockV2Error):
            self.build(observations=collision)

        legacy_entry = next(
            item for item in core["entries"] if item["dataset_family"] != "ntnu"
        )
        exact = copy.deepcopy(self.observations)
        exact[legacy_entry["target"]["path"]] = {
            "path": legacy_entry["target"]["path"],
            "sha256": legacy_entry["target"]["content_sha256"],
            "size_bytes": legacy_entry["target"]["size_bytes"],
        }
        payload = self.build(observations=exact)
        self.assertEqual(
            sum(item["state"] == "EXACT_EXISTING" for item in payload["pre_freeze_target_states"]),
            1,
        )

    def test_timestamp_authority_and_source_shape_fail_closed(self) -> None:
        with self.assertRaises(lock.B0MaterializationLockV2Error):
            lock.build_lock_payload(
                frozen_at="2026-08-08T15:30:00",
                legacy_authority=self.legacy_payload,
                effective_checksum_records=self.effective,
                frozen_queue_authority=self.queue,
                adoption_binding=self.adoption,
                review_evidence_binding=self.review,
                hf_correction_binding=self.hf,
                source_bindings=self.sources,
                target_observations=self.observations,
            )
        changed = copy.deepcopy(self.sources)
        changed.pop()
        with self.assertRaises(lock.B0MaterializationLockV2Error):
            self.build(sources=changed)
        changed_adoption = dict(self.adoption)
        changed_adoption["extra"] = False
        with self.assertRaises(lock.B0MaterializationLockV2Error):
            self.build(adoption=changed_adoption)

    def test_live_builder_blocks_v1_dual_authority_before_other_work(self) -> None:
        for collision in lock.LEGACY_OUTPUTS_FORBIDDEN:
            with self.subTest(collision=collision), mock.patch.object(
                lock.formal_io, "destination_exists"
            ) as exists, mock.patch.object(
                lock.adoption, "adoption_authority_binding"
            ) as later:
                exists.side_effect = (
                    lambda _root, relative, collision=collision: relative == collision
                )
                with self.assertRaises(FileExistsError):
                    lock.build_live_lock(
                        frozen_at="2026-08-08T15:30:00+08:00", root=lock.ROOT
                    )
                later.assert_not_called()

    def test_cli_preview_never_publishes(self) -> None:
        payload = self.build()
        with mock.patch.object(lock, "build_live_lock", return_value=payload), mock.patch.object(
            lock.formal_io, "publish_bytes_no_clobber"
        ) as publish, mock.patch("builtins.print"):
            self.assertEqual(
                lock.main(["--frozen-at", "2026-08-08T15:30:00+08:00"]), 0
            )
            publish.assert_not_called()

    def test_write_uses_pre_and_post_rebuild_guards_and_rejects_drift(self) -> None:
        payload = self.build()
        calls = []

        def fake_publish(_root, _relative, _content, **kwargs):
            kwargs["pre_link_guard"]()
            kwargs["post_link_guard"]()
            calls.append("published")
            return {"path": lock.OUTPUT_RELATIVE, "sha256": sha("f"), "size_bytes": 1}

        with mock.patch.object(lock, "build_live_lock", return_value=payload) as rebuild, mock.patch.object(
            lock.formal_io, "global_formal_lock"
        ) as flock, mock.patch.object(
            lock.formal_io, "publish_bytes_no_clobber", side_effect=fake_publish
        ), mock.patch("builtins.print"):
            flock.return_value.__enter__.return_value = None
            flock.return_value.__exit__.return_value = False
            self.assertEqual(
                lock.main(["--frozen-at", "2026-08-08T15:30:00+08:00", "--write"]),
                0,
            )
            self.assertEqual(calls, ["published"])
            self.assertEqual(rebuild.call_count, 3)

        drift = copy.deepcopy(payload)
        drift["capacity"]["required_free_bytes"] += 1
        drift[lock.SELF_HASH_FIELD] = lock.document_hash(drift, lock.SELF_HASH_FIELD)
        sequence = [payload, drift]
        with mock.patch.object(lock, "build_live_lock", side_effect=sequence), mock.patch.object(
            lock.formal_io, "global_formal_lock"
        ) as flock, mock.patch.object(lock.formal_io, "publish_bytes_no_clobber") as publish, mock.patch(
            "builtins.print"
        ):
            flock.return_value.__enter__.return_value = None
            flock.return_value.__exit__.return_value = False

            def invoke_guard(_root, _relative, _content, **kwargs):
                kwargs["pre_link_guard"]()
                return {}

            publish.side_effect = invoke_guard
            with self.assertRaises(lock.B0MaterializationLockV2Error):
                lock.main(["--frozen-at", "2026-08-08T15:30:00+08:00", "--write"])


if __name__ == "__main__":
    unittest.main()
