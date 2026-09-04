from __future__ import annotations

import unittest

from scripts.closeout_p07_b1_smoke_audit_correction_v2 import validate_precloseout


class P07B1SmokeCloseoutV2Tests(unittest.TestCase):
    def test_preserved_attempt_is_eligible_for_no_rerun_closeout(self) -> None:
        _queue, allocation, audit = validate_precloseout()
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["feature_bag"]["feature_frames"], 450)
        self.assertEqual(audit["feature_bag"]["feature_observations"], 157500)
        self.assertEqual(audit["run_id"], allocation["run_id"])


if __name__ == "__main__":
    unittest.main()
