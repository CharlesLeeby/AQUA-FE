from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_b1_klt_nativeq_current_exporter_contract_v2 as builder
from scripts import check_b1_klt_nativeq_current_exporter_contract_v2 as checker
from scripts import prove_b1_klt_exporter_transition_v2 as proof


class B1CurrentExporterContractV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = builder.build_payload()

    def _evaluate_mutation(self, mutate) -> dict[str, object]:
        payload = copy.deepcopy(self.payload)
        mutate(payload)
        payload["contract_hash"] = checker.payload_hash(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            return checker.evaluate_contract(path)

    def test_exact_four_patch_reconstruction_and_ast_isolation(self) -> None:
        value = proof.build_proof()
        self.assertTrue(value["contract_pass"])
        self.assertEqual(
            value["reconstruction"]["reconstructed_old"]["sha256"], proof.OLD_SHA256
        )
        self.assertEqual(len(value["patches_forward_order"]), 4)
        self.assertTrue(value["branch_isolation"]["klt_factory_old_equals_current"])
        self.assertTrue(
            value["branch_isolation"]["vins_pointcloud_payload_old_equals_current"]
        )

    def test_reverse_patch_rejects_context_tamper(self) -> None:
        with self.assertRaisesRegex(proof.ProofError, "PATCH_CONTEXT_MISMATCH"):
            proof.reverse_apply("wrong\n", "@@ -1,1 +1,1 @@\n-old\n+new\n")

    def test_live_contract_passes(self) -> None:
        decision = checker.evaluate_contract(builder.DEFAULT_OUTPUT)
        self.assertTrue(decision["contract_pass"], decision["reasons"])

    def test_contract_hash_tamper_fails(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["scope"] = "tampered"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            decision = checker.evaluate_contract(path)
        self.assertIn("CONTRACT_HASH_MISMATCH", decision["reasons"])

    def test_transition_proof_record_tamper_fails(self) -> None:
        decision = self._evaluate_mutation(
            lambda value: value["records"]["transition_proof"].__setitem__(
                "sha256", "0" * 64
            )
        )
        self.assertTrue(
            any(str(reason).startswith("transition_proof:SHA256_MISMATCH") for reason in decision["reasons"])
        )

    def test_vins_core_so_digest_tamper_fails(self) -> None:
        decision = self._evaluate_mutation(
            lambda value: value["vins_ldd_core"]["libvins_lib.so"].__setitem__(
                "sha256", "0" * 64
            )
        )
        self.assertTrue(
            any(str(reason).startswith("VINS_LDD:libvins_lib.so:SHA256_MISMATCH") for reason in decision["reasons"])
        )

    def test_vins_core_so_path_tamper_fails(self) -> None:
        decision = self._evaluate_mutation(
            lambda value: value["vins_ldd_core"]["libcamera_models.so"].__setitem__(
                "path", "/tmp/not-the-camera-model-library.so"
            )
        )
        self.assertIn("VINS_LDD:libcamera_models.so:PATH_MISMATCH", decision["reasons"])

    def test_transition_claim_tamper_fails(self) -> None:
        decision = self._evaluate_mutation(
            lambda value: value["transition_claim"].__setitem__("exact_patch_count", 5)
        )
        self.assertIn("TRANSITION_CLAIM_MISMATCH", decision["reasons"])

    def test_decision_write_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            checker.write_exclusive(path, {"first": True})
            with self.assertRaises(FileExistsError):
                checker.write_exclusive(path, {"second": True})

    def test_wrapper_delegates_exact_original_runner_without_old_guard(self) -> None:
        text = (
            builder.ROOT
            / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v2.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('RUNNER="$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh"', text)
        self.assertIn('exec bash "$RUNNER" external 2 4500 6300 klt 2', text)
        self.assertIn('FORCE_RAW=0 FORCE_EXPORT=0', text)
        self.assertIn('mkdir -- "$DECISION_DIR"', text)
        self.assertNotIn("run_isj_b1_klt_nativeq_guarded_v1.sh", text)


if __name__ == "__main__":
    unittest.main()
