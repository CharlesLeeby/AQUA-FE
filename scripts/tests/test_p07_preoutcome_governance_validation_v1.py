from __future__ import annotations

import unittest

from scripts.validate_p07_preoutcome_governance_v1 import build_report


class P07PreoutcomeGovernanceValidationV1Tests(unittest.TestCase):
    def test_frozen_bundle_passes_independent_validation(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertTrue(all(report["deterministic_rebuild"].values()))
        self.assertTrue(all(report["semantic_checks"].values()))
        self.assertTrue(all(row["pass"] for row in report["analysis_artifact_hashes"]))


if __name__ == "__main__":
    unittest.main()
