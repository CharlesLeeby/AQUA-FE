from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.build_nativeq_backend_contract import payload_hash, sha256
from scripts.check_nativeq_backend_contract import evaluate_contract, runtime_contract


def _runtime() -> dict[str, object]:
    return runtime_contract(
        mode="vins_safe",
        floor=0.8,
        alpha=0.65,
        raw_quality=False,
        constant_quality=False,
        scales={"learned": 1.0, "sp_lg": 1.0, "xfeat": 1.0, "loftr": 1.0},
        constants={"learned": None, "sp_lg": None, "xfeat": None, "loftr": None},
    )


class NativeQualityBackendGuardTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        backend = root / "backend"
        backend.mkdir()
        consumer = backend / "consumer.cpp"
        binary = root / "vins_node"
        exporter = root / "exporter.py"
        config = root / "frontend.yaml"
        for path, content in (
            (consumer, b"consumer"),
            (binary, b"binary"),
            (exporter, b"exporter"),
            (config, b"config"),
        ):
            path.write_bytes(content)
        contract = {
            "schema_version": "aqua-fe-backend-quality-consumer-contract-v1",
            "status": "FROZEN_DEVELOPMENT_CONSUMER_CONTRACT",
            "quality_semantics": {
                "formal_channel_required": True,
                "clip_min": 0.05,
                "clip_max": 1.0,
                "minimum_track_observations_for_factor": 4,
                "sigma_channel_consumed": False,
            },
            "expected_runtime": _runtime(),
            "consumer_files": [{"path": "consumer.cpp", "sha256": sha256(consumer)}],
            "consumer_binary": {"path": str(binary), "sha256": sha256(binary)},
            "frontend_mapper": {
                "exporter": {"path": str(exporter), "sha256": sha256(exporter)},
                "frontend_config": {"path": str(config), "sha256": sha256(config)},
            },
        }
        contract["contract_hash"] = payload_hash(contract)
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return contract_path, backend, binary, exporter, config

    def test_exact_contract_passes_and_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract, backend, binary, exporter, config = self._fixture(root)
            decision = evaluate_contract(
                contract_path=contract,
                backend_root=backend,
                binary=binary,
                exporter=exporter,
                frontend_config=config,
                runtime=_runtime(),
            )
            self.assertTrue(decision["contract_pass"])
            (backend / "consumer.cpp").write_bytes(b"changed")
            decision = evaluate_contract(
                contract_path=contract,
                backend_root=backend,
                binary=binary,
                exporter=exporter,
                frontend_config=config,
                runtime=_runtime(),
            )
            self.assertFalse(decision["contract_pass"])
            self.assertEqual(decision["action"], "FALLBACK_CLASSICAL")

    def test_runtime_drift_and_unattested_reuse_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract, backend, binary, exporter, config = self._fixture(root)
            drifted = _runtime()
            drifted["backend_quality_floor"] = 1.0
            bag = root / "features.bag"
            bag.write_bytes(b"bag")
            decision = evaluate_contract(
                contract_path=contract,
                backend_root=backend,
                binary=binary,
                exporter=exporter,
                frontend_config=config,
                runtime=drifted,
                feature_bag=bag,
            )
            self.assertIn("RUNTIME_QUALITY_MAPPING_MISMATCH", decision["reasons"])
            self.assertIn("REUSED_BAG_ATTESTATION_REQUIRED", decision["reasons"])

    def test_valid_bag_attestation_is_bound_to_bag_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path, backend, binary, exporter, config = self._fixture(root)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            bag = root / "features.bag"
            bag.write_bytes(b"bag")
            attestation = root / "attestation.json"
            attestation.write_text(
                json.dumps(
                    {
                        "schema_version": "aqua-fe-nativeq-bag-attestation-v1",
                        "contract_pass": True,
                        "backend_contract_hash": contract["contract_hash"],
                        "feature_bag_sha256": sha256(bag),
                        "runtime_quality_contract": _runtime(),
                    }
                ),
                encoding="utf-8",
            )
            decision = evaluate_contract(
                contract_path=contract_path,
                backend_root=backend,
                binary=binary,
                exporter=exporter,
                frontend_config=config,
                runtime=_runtime(),
                feature_bag=bag,
                bag_attestation=attestation,
            )
            self.assertTrue(decision["contract_pass"])
            bag.write_bytes(b"changed")
            decision = evaluate_contract(
                contract_path=contract_path,
                backend_root=backend,
                binary=binary,
                exporter=exporter,
                frontend_config=config,
                runtime=_runtime(),
                feature_bag=bag,
                bag_attestation=attestation,
            )
            self.assertIn("REUSED_FEATURE_BAG_HASH_MISMATCH", decision["reasons"])

    def test_shell_guard_never_calls_proposed_runner_on_rejection(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        wrapper = workspace / "scripts/run_isj_nativeq_contract_guarded_v4.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = root / "checker.py"
            proposed = root / "proposed.sh"
            fallback = root / "fallback.sh"
            proposed_marker = root / "proposed.marker"
            fallback_marker = root / "fallback.marker"
            checker.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")
            proposed.write_text(
                f"#!/usr/bin/env bash\ntouch '{proposed_marker}'\n", encoding="utf-8"
            )
            fallback.write_text(
                f"#!/usr/bin/env bash\ntouch '{fallback_marker}'\n", encoding="utf-8"
            )
            proposed.chmod(0o755)
            fallback.chmod(0o755)
            env = {
                **os.environ,
                "ROOT": str(workspace),
                "AQUAFE_CONTRACT_CHECKER": str(checker),
                "AQUAFE_PROPOSED_RUNNER": str(proposed),
                "AQUAFE_FALLBACK_RUNNER": str(fallback),
                "AQUAFE_DECISION_DIR": str(root / "decisions"),
            }
            completed = subprocess.run(
                ["bash", str(wrapper), "ntnu", "fjord_1", "83", "30", "hybrid_xfeat", "2"],
                cwd=workspace,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(proposed_marker.exists())
            self.assertTrue(fallback_marker.exists())


if __name__ == "__main__":
    unittest.main()
