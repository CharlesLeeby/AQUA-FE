from __future__ import annotations

import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from scripts import build_p07_backend_b0_materialization_lock_v1 as legacy
from scripts import p07_backend_b0_legacy_recipe_authority_v1 as authority
from scripts.tests import test_p07_backend_b0_plan_v2 as fixture_module


_REAL_BUILTIN_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open
_REAL_PATH_OPEN = Path.open
_REAL_VALIDATE_ARTIFACTS = legacy.queue_validator.validate_artifacts


def _is_bag_path(value: object) -> bool:
    try:
        return os.fsdecode(os.fspath(value)).lower().endswith(".bag")
    except TypeError:
        return False


def _guarded_builtin_open(file, *args, **kwargs):
    if _is_bag_path(file):
        raise AssertionError("test attempted to open a real bag: %s" % file)
    return _REAL_BUILTIN_OPEN(file, *args, **kwargs)


def _guarded_io_open(file, *args, **kwargs):
    if _is_bag_path(file):
        raise AssertionError("test attempted to io.open a real bag: %s" % file)
    return _REAL_IO_OPEN(file, *args, **kwargs)


def _guarded_os_open(path, flags, *args, **kwargs):
    if _is_bag_path(path):
        raise AssertionError("test attempted to os.open a real bag: %s" % path)
    return _REAL_OS_OPEN(path, flags, *args, **kwargs)


def _guarded_path_open(path, *args, **kwargs):
    if _is_bag_path(path):
        raise AssertionError("test attempted to Path.open a real bag: %s" % path)
    return _REAL_PATH_OPEN(path, *args, **kwargs)


def _validate_without_source_files(*args, **kwargs):
    kwargs["verify_source_files"] = False
    return _REAL_VALIDATE_ARTIFACTS(*args, **kwargs)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(path: str) -> dict:
    return {"path": path, "sha256": digest(path), "size_bytes": len(path) + 1}


def canonical_digest(value: object) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


ORACLE_RECIPES_SHA256 = (
    "920e46b79154af02ec33de5faac60f75ab39601e83254ac8eaa6df482d324a7c"
)
ORACLE_INPUT_ARTIFACTS_SHA256 = (
    "09d82d084f7993234577c0dc7cf3034ee1d464afd8ee19d6d7837754f57123d6"
)
ORACLE_INPUT_PATHS_SHA256 = (
    "b9805a545cf955a916f9657bd6bc2c798ef84ec4a5bee12b5d9c8eaec15566a1"
)
ORACLE_DEPENDENCIES_SHA256 = (
    "bdfb905649604cc47976b0eb1462c87cff7ca2f8279fb687e4eeda7d5c105196"
)


class LegacyRecipeAuthorityV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._global_guard_patchers = [
            mock.patch.object(builtins, "open", side_effect=_guarded_builtin_open),
            mock.patch.object(io, "open", side_effect=_guarded_io_open),
            mock.patch.object(os, "open", side_effect=_guarded_os_open),
            mock.patch.object(
                Path, "open", autospec=True, side_effect=_guarded_path_open
            ),
            mock.patch.object(
                legacy.queue_validator,
                "validate_artifacts",
                side_effect=_validate_without_source_files,
            ),
        ]
        for patcher in cls._global_guard_patchers:
            patcher.start()
        try:
            fixture = fixture_module.P07BackendB0PlanV2Tests(methodName="runTest")
            fixture.setUp()
            recipes = copy.deepcopy(fixture.recipes)
            afrl = recipes[0]
            afrl["evidence"][2].update(
                {
                    "classification": "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME",
                    "vins_csv_absent": True,
                    "vins_output_empty": True,
                }
            )
            afrl["recipe_hash"] = legacy.document_hash(afrl, "recipe_hash")
            by_window = {item["window_id"]: item for item in recipes}

            def aqualoc_recipe(window, *_args, **_kwargs):
                return copy.deepcopy(by_window[window["window_id"]])

            def afrl_recipe(window, *_args, **_kwargs):
                return copy.deepcopy(by_window[window["window_id"]])

            with mock.patch.object(
                legacy, "_aqualoc_recipe", side_effect=aqualoc_recipe
            ), mock.patch.object(
                authority, "_build_afrl_recipe", side_effect=afrl_recipe
            ), mock.patch.object(
                legacy,
                "_direct_recipe",
                side_effect=AssertionError("NTNU helper called"),
            ), mock.patch.object(
                legacy,
                "_bag_input_contract_bytes",
                side_effect=AssertionError("bag parser called"),
            ):
                official = authority.build_live_authority(authority.ROOT)

            independent = {
                "recipes": canonical_digest(official["recipes"]),
                "input_artifacts": canonical_digest(official["input_artifacts"]),
                "input_paths": canonical_digest(
                    [item["path"] for item in official["input_artifacts"]]
                ),
                "dependencies": canonical_digest(official["dependency_sources"]),
            }
            expected = {
                "recipes": ORACLE_RECIPES_SHA256,
                "input_artifacts": ORACLE_INPUT_ARTIFACTS_SHA256,
                "input_paths": ORACLE_INPUT_PATHS_SHA256,
                "dependencies": ORACLE_DEPENDENCIES_SHA256,
            }
            if independent != expected:
                raise AssertionError(
                    "independent frozen-authority oracle drift: %r" % independent
                )
            cls.official_artifacts = copy.deepcopy(official["input_artifacts"])
            cls.official_dependencies = copy.deepcopy(official["dependency_sources"])
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        for patcher in reversed(getattr(cls, "_global_guard_patchers", [])):
            patcher.stop()
        cls._global_guard_patchers = []

    def setUp(self) -> None:
        # Reuse the small, in-memory legacy recipe fixtures already accepted by
        # the canonical v1 validator.  No dataset bag is opened by this setup.
        fixture = fixture_module.P07BackendB0PlanV2Tests(methodName="runTest")
        fixture.setUp()
        self.recipes = copy.deepcopy(fixture.recipes)
        afrl = self.recipes[0]
        afrl["evidence"][2].update(
            {
                "classification": "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME",
                "vins_csv_absent": True,
                "vins_output_empty": True,
            }
        )
        afrl["recipe_hash"] = legacy.document_hash(afrl, "recipe_hash")
        self.bindings = [
            copy.deepcopy(item)
            for item in fixture.v1_plan["queue_bindings"]
            if item["window_id"] in authority.WINDOWS
        ]
        for binding in self.bindings:
            binding["queue_index"] = int(binding["queue_index"])
        self.artifacts = copy.deepcopy(type(self).official_artifacts)
        self.dependencies = copy.deepcopy(type(self).official_dependencies)

    def build(self, **overrides) -> dict:
        return authority.build_authority_payload(
            recipes=overrides.get("recipes", self.recipes),
            queue_bindings=overrides.get("bindings", self.bindings),
            input_artifacts=overrides.get("artifacts", self.artifacts),
            dependency_sources=overrides.get("dependencies", self.dependencies),
        )

    def test_exact_17_authority_is_nonformal_and_preserves_v1_recipes(self) -> None:
        payload = self.build()
        self.assertEqual(
            payload["queue_bindings_sha256"],
            authority.FROZEN_LEGACY_B0_BINDINGS_SHA256,
        )
        self.assertEqual(payload["recipes_sha256"], ORACLE_RECIPES_SHA256)
        self.assertEqual(
            payload["input_artifact_paths_sha256"], ORACLE_INPUT_PATHS_SHA256
        )
        self.assertEqual(
            payload["input_artifacts_sha256"], ORACLE_INPUT_ARTIFACTS_SHA256
        )
        self.assertEqual(
            payload["dependency_sources_sha256"], ORACLE_DEPENDENCIES_SHA256
        )
        self.assertEqual(payload["recipes"], self.recipes)
        self.assertEqual(len(payload["recipes"]), 17)
        self.assertEqual(len(payload["queue_bindings"]), 51)
        self.assertEqual(
            authority.validate_authority_payload(payload),
            payload[authority.SELF_HASH_FIELD],
        )
        self.assertEqual(payload["ntnu_recipe_count"], 0)
        self.assertTrue(payload["policy"]["ntnu_excluded"])
        self.assertFalse(payload["policy"]["materialization_authorized"])
        self.assertFalse(payload["policy"]["vins_execution_authorized"])
        self.assertFalse(payload["policy"]["formal_artifact_published"])
        for recipe in payload["recipes"]:
            self.assertEqual(
                recipe["recipe_hash"], legacy.document_hash(recipe, "recipe_hash")
            )

    def test_pure_builder_opens_no_file_and_never_calls_ntnu_helper(self) -> None:
        with mock.patch.object(
            builtins, "open", side_effect=AssertionError("pure builder opened a file")
        ), mock.patch.object(
            legacy,
            "_direct_recipe",
            side_effect=AssertionError("NTNU direct recipe helper was called"),
        ), mock.patch.object(
            legacy,
            "_bag_input_contract_bytes",
            side_effect=AssertionError("pure builder inspected a bag"),
        ):
            payload = self.build()
        self.assertEqual(payload["ntnu_recipe_count"], 0)

    def test_live_preview_selects_17_before_helpers_and_never_touches_ntnu(self) -> None:
        recipes = {item["window_id"]: item for item in self.recipes}

        def aqualoc_recipe(window, *_args, **_kwargs):
            return copy.deepcopy(recipes[window["window_id"]])

        def afrl_recipe(window, *_args, **_kwargs):
            return copy.deepcopy(recipes[window["window_id"]])

        with mock.patch.object(
            legacy, "_aqualoc_recipe", side_effect=aqualoc_recipe
        ) as aqualoc, mock.patch.object(
            authority, "_build_afrl_recipe", side_effect=afrl_recipe
        ) as afrl, mock.patch.object(
            legacy,
            "_direct_recipe",
            side_effect=AssertionError("NTNU direct helper must remain unreachable"),
        ), mock.patch.object(
            legacy,
            "_bag_input_contract_bytes",
            side_effect=AssertionError("live fixture must not inspect any bag"),
        ):
            payload = authority.build_live_authority(authority.ROOT)
        self.assertEqual(aqualoc.call_count, 16)
        self.assertEqual(afrl.call_count, 1)
        self.assertEqual(payload["recipe_count"], 17)
        self.assertEqual(payload["ntnu_recipe_count"], 0)

    def test_unknown_ntnu_duplicate_and_order_drift_are_rejected(self) -> None:
        unknown = copy.deepcopy(self.recipes)
        unknown[0]["window_id"] = "ntnu:fjord_6:0001"
        unknown[0]["recipe_hash"] = legacy.document_hash(
            unknown[0], "recipe_hash"
        )
        duplicate = copy.deepcopy(self.recipes)
        duplicate[-1] = copy.deepcopy(duplicate[0])
        reversed_recipes = list(reversed(copy.deepcopy(self.recipes)))
        for recipes in (unknown, duplicate, reversed_recipes):
            with self.subTest(first=recipes[0]["window_id"]):
                with self.assertRaises(authority.LegacyRecipeAuthorityError):
                    self.build(recipes=recipes)

    def test_source_reference_target_and_nested_schema_drift_are_rejected(self) -> None:
        variants = []
        source = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in source
            if item["window_id"] == "aqualoc_harbor:H06:0000"
        )
        attacker = "datasets/attacker/archive.tar.gz"
        recipe["source_raw_path"] = attacker
        recipe["source_path_identity"]["path"] = attacker
        argv = recipe["converter_argv_template"]
        argv[argv.index("--input") + 1] = attacker
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")
        variants.append(source)

        reference = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in reference
            if item["window_id"] == "aqualoc_archaeology:A01:0003"
        )
        argv = recipe["converter_argv_template"]
        argv[argv.index("--gt-txt") + 1] = "datasets/attacker/gt.txt"
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")
        variants.append(reference)

        target = copy.deepcopy(self.recipes)
        target[1]["target_path"] = "datasets/attacker/window.bag"
        target[1]["recipe_hash"] = legacy.document_hash(target[1], "recipe_hash")
        variants.append(target)

        nested = copy.deepcopy(self.recipes)
        nested[1]["source_path_identity"]["unexpected"] = True
        nested[1]["recipe_hash"] = legacy.document_hash(nested[1], "recipe_hash")
        variants.append(nested)

        a04 = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in a04
            if item["window_id"] == "aqualoc_archaeology:A04:0002"
        )
        recipe["a04_layout_recovery"]["unexpected"] = True
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")
        variants.append(a04)

        for recipes in variants:
            with self.assertRaises(authority.LegacyRecipeAuthorityError):
                self.build(recipes=recipes)

    def test_afrl_contract_manifest_evidence_and_provenance_drift_are_rejected(self) -> None:
        variants = []
        contract = copy.deepcopy(self.recipes)
        contract[0]["source_input_contract"]["topic_counts"]["/imu/imu"] += 1
        contract[0]["recipe_hash"] = legacy.document_hash(contract[0], "recipe_hash")
        variants.append((contract, self.bindings))

        evidence = copy.deepcopy(self.recipes)
        evidence[0]["evidence"][0]["unexpected"] = True
        evidence[0]["recipe_hash"] = legacy.document_hash(evidence[0], "recipe_hash")
        variants.append((evidence, self.bindings))

        provenance = copy.deepcopy(self.recipes)
        provenance[1]["source_provenance_hash"] = "0" * 64
        provenance[1]["recipe_hash"] = legacy.document_hash(
            provenance[1], "recipe_hash"
        )
        variants.append((provenance, self.bindings))

        binding = copy.deepcopy(self.bindings)
        binding[0]["source_provenance_hash"] = "0" * 64
        variants.append((self.recipes, binding))

        both_recipes = copy.deepcopy(self.recipes)
        both_bindings = copy.deepcopy(self.bindings)
        window_id = both_recipes[1]["window_id"]
        both_recipes[1]["source_provenance_hash"] = "1" * 64
        both_recipes[1]["recipe_hash"] = legacy.document_hash(
            both_recipes[1], "recipe_hash"
        )
        for item in both_bindings:
            if item["window_id"] == window_id:
                item["source_provenance_hash"] = "1" * 64
        variants.append((both_recipes, both_bindings))

        for recipes, bindings in variants:
            with self.assertRaises(authority.LegacyRecipeAuthorityError):
                self.build(recipes=recipes, bindings=bindings)

    def test_artifact_dependency_and_rehashed_payload_drift_are_rejected(self) -> None:
        missing = self.artifacts[:-1]
        with self.assertRaises(authority.LegacyRecipeAuthorityError):
            self.build(artifacts=missing)
        with self.assertRaises(authority.LegacyRecipeAuthorityError):
            self.build(dependencies=self.dependencies[:-1])

        payload = self.build()
        altered = copy.deepcopy(payload)
        altered["policy"]["vins_execution_authorized"] = True
        altered[authority.SELF_HASH_FIELD] = authority.document_hash(
            altered, authority.SELF_HASH_FIELD
        )
        with self.assertRaises(authority.LegacyRecipeAuthorityError):
            authority.validate_authority_payload(altered)

    def test_all_external_authority_recompute_drifts_are_rejected(self) -> None:
        dependency = copy.deepcopy(self.dependencies)
        dependency[0]["sha256"] = "f" * 64
        dependency[0]["size_bytes"] += 9

        governance = copy.deepcopy(self.artifacts)
        governance[0]["sha256"] = "e" * 64
        governance[0]["size_bytes"] += 7

        extra_ntnu = copy.deepcopy(self.artifacts)
        extra_ntnu.append(record("datasets/ntnu/attacker_input.bin"))

        topic_count = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in topic_count
            if item["window_id"] == "aqualoc_archaeology:A01:0003"
        )
        recipe["expected_topic_counts"]["/rtimulib_node/imu"] += 1
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")

        raw_identity = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in raw_identity
            if item["window_id"] == "aqualoc_archaeology:A01:0003"
        )
        replacement = "d" * 64
        recipe["source_raw_sha256"] = replacement
        recipe["source_path_identity"]["expected_sha256"] = replacement
        recipe["source_path_identity"]["observed_sha256"] = replacement
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")

        target_identity = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in target_identity
            if item["window_id"] == "aqualoc_archaeology:A01:0003"
        )
        recipe["expected_sha256"] = "c" * 64
        recipe["expected_size_bytes"] += 1
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")

        a04_evidence = copy.deepcopy(self.recipes)
        recipe = next(
            item for item in a04_evidence
            if item["window_id"] == "aqualoc_archaeology:A04:0002"
        )
        recipe["a04_layout_recovery"]["q55_recovery_lock"]["sha256"] = "b" * 64
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")

        afrl_evidence = copy.deepcopy(self.recipes)
        afrl_evidence[0]["evidence"][0]["sha256"] = "a" * 64
        afrl_evidence[0]["recipe_hash"] = legacy.document_hash(
            afrl_evidence[0], "recipe_hash"
        )

        cases = (
            ("dependency hash/size", {"dependencies": dependency}),
            ("governance artifact hash/size", {"artifacts": governance}),
            ("extra NTNU artifact", {"artifacts": extra_ntnu}),
            ("AQUALOC IMU topic count", {"recipes": topic_count}),
            ("AQUALOC raw identity hash", {"recipes": raw_identity}),
            ("AQUALOC target hash/size", {"recipes": target_identity}),
            ("A04 recovery evidence", {"recipes": a04_evidence}),
            ("AFRL evidence", {"recipes": afrl_evidence}),
        )
        for name, overrides in cases:
            with self.subTest(name=name):
                with self.assertRaises(authority.LegacyRecipeAuthorityError):
                    self.build(**overrides)


if __name__ == "__main__":
    unittest.main()
