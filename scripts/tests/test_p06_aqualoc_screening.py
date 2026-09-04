#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_p06_aqualoc_screening import audit_metrics


HEADER = (
    "frame_index,tracker_mode,grid_coverage,dropout_ratio,"
    "flat_region_ratio,degradation_score,xfeat_tracks\n"
)


class P06AqualocScreeningTest(unittest.TestCase):
    def test_contract_accepts_klt_only_bounded_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.csv"
            path.write_text(HEADER + "0,klt,0.5,0.0,0.2,0.3,0\n", encoding="utf-8")
            audit = audit_metrics(path)
            self.assertTrue(audit["contract_pass"])

    def test_contract_rejects_learned_or_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.csv"
            path.write_text(HEADER + "0,klt,1.2,0.0,0.2,0.3,1\n", encoding="utf-8")
            audit = audit_metrics(path)
            self.assertFalse(audit["contract_pass"])
            self.assertIn("learned_nonzero_cells:1", audit["issues"])


if __name__ == "__main__":
    unittest.main()
