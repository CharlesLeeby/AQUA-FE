from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_b0_vins_origin_identity_v1 import (
    DEFAULT_BACKEND_ROOT,
    DEFAULT_BINARY,
    DEFAULT_CONTRACT,
    DEFAULT_VINS_WORKSPACE,
    evaluate_b0_identity,
)
from scripts.check_b1_klt_nativeq_contract_v1 import evaluate_b1
from scripts.check_nativeq_backend_contract import (
    DEFAULT_CONFIG,
    DEFAULT_EXPORTER,
)


ROOT = Path(__file__).resolve().parents[2]


class P07B0B1ExecutionGuardTests(unittest.TestCase):
    def test_actual_b0_and_b1_identities_pass(self) -> None:
        b0 = evaluate_b0_identity(
            contract_path=DEFAULT_CONTRACT,
            vins_workspace=DEFAULT_VINS_WORKSPACE,
            backend_root=DEFAULT_BACKEND_ROOT,
            binary=DEFAULT_BINARY,
        )
        self.assertTrue(b0["contract_pass"], b0["reasons"])
        b1 = evaluate_b1(
            contract_path=DEFAULT_CONTRACT,
            backend_root=DEFAULT_BACKEND_ROOT,
            binary=DEFAULT_BINARY,
            exporter=DEFAULT_EXPORTER,
            frontend_config=DEFAULT_CONFIG,
        )
        self.assertTrue(b1["contract_pass"], b1["reasons"])
        self.assertFalse(b1["counts_as_proposed_result"])

    def test_b0_and_b1_binary_mismatch_fail_closed(self) -> None:
        missing = Path("/tmp/not-the-frozen-vins-node")
        b0 = evaluate_b0_identity(
            contract_path=DEFAULT_CONTRACT,
            vins_workspace=DEFAULT_VINS_WORKSPACE,
            backend_root=DEFAULT_BACKEND_ROOT,
            binary=missing,
        )
        self.assertFalse(b0["contract_pass"])
        b1 = evaluate_b1(
            contract_path=DEFAULT_CONTRACT,
            backend_root=DEFAULT_BACKEND_ROOT,
            binary=missing,
            exporter=DEFAULT_EXPORTER,
            frontend_config=DEFAULT_CONFIG,
        )
        self.assertFalse(b1["contract_pass"])

    def test_wrappers_reject_when_checker_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = root / "reject.py"
            checker.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")
            for script, variable in (
                ("run_isj_b0_native_vins_guarded_v1.sh", "AQUAFE_B0_CHECKER"),
                ("run_isj_b1_klt_nativeq_guarded_v1.sh", "AQUAFE_B1_CHECKER"),
            ):
                env = {
                    **os.environ,
                    "AQUAFE_P07_TEST_HOOKS": "1",
                    variable: str(checker),
                    "AQUAFE_DRY_RUN": "1",
                }
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts" / script),
                        "ntnu",
                        "fjord_6",
                        "135",
                        "45",
                        "2",
                    ],
                    cwd=ROOT,
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 42, completed.stderr)


if __name__ == "__main__":
    unittest.main()
