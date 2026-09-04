from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_p04_v3_control_identifiability import (
    DEFAULT_LOCK,
    ROOT,
    build_report,
    function_source,
)


class P04V3ControlIdentifiabilityTests(unittest.TestCase):
    def test_frozen_repository_decision_is_reproducible(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            report["decision"],
            "STRICT_MATCHED_CLASSICAL_CONTROL_NOT_IDENTIFIABLE_UNDER_V3",
        )
        self.assertEqual(
            report["recommended_disposition"]["H2_CONTROL_CONTRACT"],
            "NOT_APPLICABLE_CARRIER_FEEDBACK",
        )
        self.assertFalse(report["learned_outcome_read"])
        self.assertFalse(report["trajectory_outcome_read"])

    def test_method_lock_drift_fails_closed(self) -> None:
        data = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
        data["method_identity"]["selector"] = "drifted"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            report = build_report(path)
        self.assertEqual(report["status"], "REVISE")
        self.assertEqual(report["decision"], "IDENTIFIABILITY_UNRESOLVED")

    def test_function_extraction_is_scoped(self) -> None:
        source = function_source(
            ROOT / "uw_frontend/tracking/hybrid_tracker.py",
            "HybridKltOrbTracker",
            "_append_to_klt_state",
        )
        self.assertIn("self.klt.points", source)
        self.assertNotIn("def _assign_fresh_klt_ids", source)


if __name__ == "__main__":
    unittest.main()
