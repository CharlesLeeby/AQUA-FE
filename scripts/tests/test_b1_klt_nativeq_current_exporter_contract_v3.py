from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_b1_klt_nativeq_current_exporter_contract_v3 as builder
from scripts import check_b1_klt_nativeq_current_exporter_contract_v2 as common
from scripts import check_b1_klt_nativeq_current_exporter_contract_v3 as checker


class B1CurrentExporterContractV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = builder.build_payload()

    def evaluate_mutation(self, mutate) -> dict[str, object]:
        payload = copy.deepcopy(self.payload)
        mutate(payload)
        payload["contract_hash"] = common.payload_hash(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutated.json"
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            return checker.evaluate_contract(path)

    def assert_rejected(self, decision: dict[str, object], token: str) -> None:
        self.assertFalse(decision["contract_pass"], decision)
        self.assertTrue(
            any(token in str(reason) for reason in decision["reasons"]),
            decision["reasons"],
        )

    def test_live_v3_contract_passes(self) -> None:
        decision = checker.evaluate_contract(builder.DEFAULT_OUTPUT)
        self.assertTrue(decision["contract_pass"], decision["reasons"])

    def test_empty_records_rejected(self) -> None:
        decision = self.evaluate_mutation(lambda value: value.__setitem__("records", {}))
        self.assert_rejected(decision, "RECORD_KEYSET_MISMATCH")

    def test_missing_transition_proof_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["records"].pop("transition_proof")
        )
        self.assert_rejected(decision, "TRANSITION_PROOF_REQUIRED")

    def test_missing_base_contract_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["records"].pop("base_contract_v1")
        )
        self.assert_rejected(decision, "BASE_CONTRACT_REQUIRED")

    def test_missing_vins_node_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["records"].pop("vins_node")
        )
        self.assert_rejected(decision, "VINS_NODE_REQUIRED")

    def test_empty_vins_ldd_core_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value.__setitem__("vins_ldd_core", {})
        )
        self.assert_rejected(decision, "VINS_LDD_KEYSET_MISMATCH")

    def test_missing_libvins_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["vins_ldd_core"].pop("libvins_lib.so")
        )
        self.assert_rejected(decision, "VINS_LDD_KEYSET_MISMATCH")

    def test_missing_camera_models_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["vins_ldd_core"].pop("libcamera_models.so")
        )
        self.assert_rejected(decision, "VINS_LDD_KEYSET_MISMATCH")

    def test_empty_consumer_files_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value.__setitem__("consumer_files", [])
        )
        self.assert_rejected(decision, "CONSUMER_FILES_EXACT_TEN_REQUIRED")

    def test_self_hashed_algorithm_mutation_rejected(self) -> None:
        def mutate(value: dict[str, object]) -> None:
            settings = value["algorithm_settings"]
            settings["export_max_features"] = 1
            settings["settings_sha256"] = checker._settings_hash(settings)

        decision = self.evaluate_mutation(mutate)
        self.assert_rejected(decision, "ALGORITHM_SETTINGS_EXACT_MISMATCH")

    def test_empty_execution_governance_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value.__setitem__("execution_governance", {})
        )
        self.assert_rejected(decision, "EXECUTION_GOVERNANCE_EXACT_MISMATCH")

    def test_extra_record_key_rejected(self) -> None:
        decision = self.evaluate_mutation(
            lambda value: value["records"].__setitem__(
                "unbound_extra", value["records"]["current_exporter"]
            )
        )
        self.assert_rejected(decision, "RECORD_KEYSET_MISMATCH")

    def test_wrapper_uses_env_i_and_fixed_sensitive_values(self) -> None:
        text = (
            builder.ROOT
            / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("env -i", text)
        self.assertIn('RAW_BAG="$RAW_BAG_FIXED"', text)
        self.assertIn("FEATURE_BAG_OVERRIDE=", text)
        self.assertIn("EXPORT_START_OFFSET= EXPORT_DURATION=", text)
        self.assertIn("EXPORT_MIN_AGE=2 ZERO_VELOCITY=0", text)
        self.assertIn('exec "${runner_env[@]}" /bin/bash "$RUNNER" external 2 4500 6300 klt 2', text)
        self.assertNotIn("${FEATURE_BAG_OVERRIDE", text)
        self.assertNotIn("${EXPORT_MIN_AGE", text)
        self.assertNotIn("${ZERO_VELOCITY", text)


if __name__ == "__main__":
    unittest.main()
