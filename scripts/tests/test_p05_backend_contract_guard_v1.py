from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.build_nativeq_backend_contract import sha256
from scripts.check_nativeq_backend_contract import runtime_contract
from scripts.check_p05_xfeat_backend_contract_v1 import (
    attestation_payload_hash,
    evaluate_contract,
    producer_identity,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT
    / "papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json"
)
VINS_WORKSPACE = Path("/home/ma/SLAM/VINS-Fusion-origin")
BACKEND_ROOT = VINS_WORKSPACE / "src/VINS-Fusion-master"
BINARY = VINS_WORKSPACE / "devel/lib/vins/vins_node"
EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
P05_CONFIG = ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"


def _backend_runtime() -> dict[str, object]:
    return runtime_contract(
        mode="vins_safe",
        floor=0.8,
        alpha=0.65,
        raw_quality=False,
        constant_quality=False,
        scales={"learned": 1.0, "sp_lg": 1.0, "xfeat": 1.0, "loftr": 1.0},
        constants={"learned": None, "sp_lg": None, "xfeat": None, "loftr": None},
    )


def _frontend_runtime() -> dict[str, object]:
    return {
        "method": "xfeat",
        "preprocess": "adaptive_clahe",
        "process_skipped_frames": True,
        "measurement_selection": False,
        "formal_three_layer_export": False,
        "vins_safe_source_selection": False,
        "export_max_features": 350,
        "vins_max_cnt": 350,
        "semidense_fallback_method": "none",
        "vins_multiple_thread": False,
        "export_features": True,
        "force_fresh_export_without_override": True,
    }


def _evaluate(**overrides):
    values = {
        "contract_path": CONTRACT_PATH,
        "workspace_root": ROOT,
        "vins_workspace": VINS_WORKSPACE,
        "backend_root": BACKEND_ROOT,
        "binary": BINARY,
        "exporter": EXPORTER,
        "frontend_config": P05_CONFIG,
        "family": "ntnu",
        "every_n": 2,
        "frame_offset": 1,
        "backend_runtime": _backend_runtime(),
        "frontend_runtime": _frontend_runtime(),
        "run_vins": False,
    }
    values.update(overrides)
    return evaluate_contract(**values)


class P05BackendContractGuardTests(unittest.TestCase):
    def test_frozen_contract_passes_without_running_vins(self) -> None:
        decision = _evaluate()
        self.assertTrue(decision["contract_pass"], decision["reasons"])
        self.assertEqual(decision["action"], "ALLOW_M_XFEAT")
        self.assertTrue(decision["counts_as_modern_baseline"])

    def test_binary_runtime_and_sampling_drift_fail_closed(self) -> None:
        runtime = _backend_runtime()
        runtime["backend_quality_floor"] = 1.0
        frontend = _frontend_runtime()
        frontend["export_max_features"] = 349
        decision = _evaluate(
            binary=Path("/tmp/not-the-frozen-vins-node"),
            backend_runtime=runtime,
            frontend_runtime=frontend,
            every_n=3,
        )
        self.assertFalse(decision["contract_pass"])
        self.assertIn("CONSUMER_BINARY:PATH_MISMATCH:/tmp/not-the-frozen-vins-node", decision["reasons"])
        self.assertIn("BACKEND_RUNTIME_MISMATCH", decision["reasons"])
        self.assertIn("P05_FRONTEND_RUNTIME_MISMATCH", decision["reasons"])
        self.assertIn("P05_EVERY_N_MISMATCH", decision["reasons"])
        self.assertEqual(decision["action"], "FALLBACK_CLASSICAL")
        self.assertFalse(decision["counts_as_modern_baseline"])

    def test_reused_bag_requires_hash_bound_p05_attestation(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / "features.bag"
            metrics = root / "frontend_metrics.csv"
            attestation = root / "attestation.json"
            bag.write_bytes(b"frozen-p05-bag")
            metrics.write_bytes(b"exported_features\n1\n")

            missing = _evaluate(feature_bag=bag)
            self.assertIn("REUSED_BAG_ATTESTATION_REQUIRED", missing["reasons"])

            payload: dict[str, object] = {
                "schema_version": "aqua-fe-p05-xfeat-bag-attestation-v1",
                "status": "PASS",
                "contract_pass": True,
                "baseline_id": contract["baseline_id"],
                "backend_contract_hash": contract["contract_hash"],
                "feature_bag": str(bag),
                "feature_bag_sha256": sha256(bag),
                "feature_bag_size_bytes": bag.stat().st_size,
                "frontend_metrics": str(metrics),
                "frontend_metrics_sha256": sha256(metrics),
                "frontend_metrics_size_bytes": metrics.stat().st_size,
                "backend_runtime": _backend_runtime(),
                "frontend_runtime": _frontend_runtime(),
                "producer_identity": producer_identity(contract),
                "bag_audit": {"status": "PASS"},
            }
            payload["attestation_hash"] = attestation_payload_hash(payload)
            attestation.write_text(json.dumps(payload), encoding="utf-8")

            passed = _evaluate(feature_bag=bag, bag_attestation=attestation)
            self.assertTrue(passed["contract_pass"], passed["reasons"])
            bag.write_bytes(b"mutated-after-attestation")
            rejected = _evaluate(feature_bag=bag, bag_attestation=attestation)
            self.assertIn("REUSED_FEATURE_BAG_HASH_MISMATCH", rejected["reasons"])
            self.assertIn("REUSED_FEATURE_BAG_SIZE_MISMATCH", rejected["reasons"])

    def test_attestation_document_mutation_fails_closed(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / "features.bag"
            metrics = root / "frontend_metrics.csv"
            attestation = root / "attestation.json"
            bag.write_bytes(b"bag")
            metrics.write_bytes(b"metrics")
            payload: dict[str, object] = {
                "schema_version": "aqua-fe-p05-xfeat-bag-attestation-v1",
                "status": "PASS",
                "contract_pass": True,
                "baseline_id": contract["baseline_id"],
                "backend_contract_hash": contract["contract_hash"],
                "feature_bag_sha256": sha256(bag),
                "feature_bag_size_bytes": bag.stat().st_size,
                "frontend_metrics": str(metrics),
                "frontend_metrics_sha256": sha256(metrics),
                "backend_runtime": _backend_runtime(),
                "frontend_runtime": _frontend_runtime(),
                "producer_identity": producer_identity(contract),
                "bag_audit": {"status": "PASS"},
            }
            payload["attestation_hash"] = attestation_payload_hash(payload)
            payload["baseline_id"] = "forged-after-hash"
            attestation.write_text(json.dumps(payload), encoding="utf-8")
            decision = _evaluate(feature_bag=bag, bag_attestation=attestation)
            self.assertIn("REUSED_BAG_ATTESTATION_HASH_MISMATCH", decision["reasons"])
            self.assertIn("REUSED_BAG_BASELINE_ID_MISMATCH", decision["reasons"])

    def test_wrapper_pass_calls_only_the_p05_runner(self) -> None:
        completed, markers = self._run_wrapper(checker_exit=0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(markers["p05"].exists())
        self.assertFalse(markers["fallback"].exists())

    def test_wrapper_rejection_routes_only_to_bag_free_fallback(self) -> None:
        completed, markers = self._run_wrapper(checker_exit=42, feature_bag=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(markers["p05"].exists())
        self.assertTrue(markers["fallback"].exists())
        fallback_env = markers["fallback"].read_text(encoding="utf-8")
        self.assertIn("feature_bag=", fallback_env)
        self.assertIn("label=KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED", fallback_env)
        self.assertIn("counts=0", fallback_env)

    def test_guard_only_rejection_is_nonzero_and_calls_no_runner(self) -> None:
        completed, markers = self._run_wrapper(checker_exit=42, guard_only=True)
        self.assertEqual(completed.returncode, 42, completed.stderr)
        self.assertFalse(markers["p05"].exists())
        self.assertFalse(markers["fallback"].exists())

    def test_independent_fallback_maps_p05_args_and_clears_learned_bag(self) -> None:
        fallback = ROOT / "scripts/run_p05_classical_contract_fallback_v2.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generic = root / "generic.sh"
            record = root / "record.txt"
            generic.write_text(
                "#!/usr/bin/env bash\n"
                f"printf 'args=%s\\nfeature_bag=%s\\nlabel=%s\\ncounts=%s\\n' "
                '"$*" "${FEATURE_BAG_OVERRIDE:-}" "${P05_GUARD_RESULT_LABEL:-}" '
                f'"${{COUNTS_AS_MODERN_BASELINE:-}}" > \'{record}\'\n',
                encoding="utf-8",
            )
            generic.chmod(0o755)
            env = {
                **os.environ,
                "AQUAFE_P05_TEST_HOOKS": "1",
                "AQUAFE_P05_GENERIC_FALLBACK_RUNNER": str(generic),
                "FEATURE_BAG_OVERRIDE": str(root / "learned.bag"),
                "P05_QUALITY_CONTRACT_ATTESTATION": str(root / "attestation.json"),
            }
            completed = subprocess.run(
                ["bash", str(fallback), "afrl", "cemetery", "0", "10", "2"],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            values = record.read_text(encoding="utf-8")
            self.assertIn("args=afrl_dataset cemetery 0 10 p05_m_rejected 2", values)
            self.assertIn("feature_bag=\n", values)
            self.assertIn("label=KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED", values)
            self.assertIn("counts=0", values)

    def _run_wrapper(
        self, *, checker_exit: int, feature_bag: bool = False, guard_only: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Path]]:
        wrapper = ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh"
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        checker = root / "checker.py"
        p05 = root / "p05.sh"
        fallback = root / "fallback.sh"
        p05_marker = root / "p05.marker"
        fallback_marker = root / "fallback.marker"
        checker.write_text(f"import sys\nsys.exit({checker_exit})\n", encoding="utf-8")
        p05.write_text(
            f"#!/usr/bin/env bash\ntouch '{p05_marker}'\n", encoding="utf-8"
        )
        fallback.write_text(
            "#!/usr/bin/env bash\n"
            f"printf 'feature_bag=%s\\nlabel=%s\\ncounts=%s\\n' "
            '"${FEATURE_BAG_OVERRIDE:-}" "${P05_GUARD_RESULT_LABEL:-}" '
            f'"${{COUNTS_AS_MODERN_BASELINE:-}}" > \'{fallback_marker}\'\n',
            encoding="utf-8",
        )
        p05.chmod(0o755)
        fallback.chmod(0o755)
        env = {
            **os.environ,
            "AQUAFE_P05_CONTRACT_CHECKER": str(checker),
            "AQUAFE_P05_RUNNER": str(p05),
            "AQUAFE_P05_FALLBACK_RUNNER": str(fallback),
            "AQUAFE_P05_DECISION_DIR": str(root / "decisions"),
            "AQUAFE_P05_TEST_HOOKS": "1",
        }
        if feature_bag:
            env["FEATURE_BAG_OVERRIDE"] = str(root / "learned-features.bag")
            env["P05_QUALITY_CONTRACT_ATTESTATION"] = str(root / "attestation.json")
        if guard_only:
            env["AQUAFE_P05_GUARD_ONLY"] = "1"
        completed = subprocess.run(
            [
                "bash",
                str(wrapper),
                "ntnu",
                "fjord_1",
                "83",
                "10",
                "2",
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed, {"p05": p05_marker, "fallback": fallback_marker}


if __name__ == "__main__":
    unittest.main()
