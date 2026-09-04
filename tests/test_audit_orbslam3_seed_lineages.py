from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_orbslam3_seed_lineages import audit_group, load_image_frames


class OrbSlam3SeedLineageAuditTest(unittest.TestCase):
    def test_reports_native_frame_span_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            times = root / "times.txt"
            seeds = root / "seeds.txt"
            times.write_text("100\n200\n300\n400\n", encoding="ascii")
            seeds.write_text(
                "# timestamp_ns p_u p_v feature_id quality\n"
                "100 1 2 7 0.8\n"
                "300 3 4 7 1.0\n"
                "400 5 6 9 0.6\n",
                encoding="ascii",
            )

            rows = audit_group("case", seeds, times)

        self.assertEqual([row["feature_id"] for row in rows], [7, 9])
        self.assertEqual(rows[0]["observations"], 2)
        self.assertEqual(rows[0]["first_frame"], 0)
        self.assertEqual(rows[0]["last_frame"], 2)
        self.assertEqual(rows[0]["frame_span"], 3)
        self.assertAlmostEqual(rows[0]["quality_median"], 0.9)

    def test_rejects_unmapped_seed_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            times = root / "times.txt"
            seeds = root / "seeds.txt"
            times.write_text("100\n", encoding="ascii")
            seeds.write_text("200 1 2 7 0.8\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "absent"):
                audit_group("case", seeds, times)

    def test_rejects_duplicate_image_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            times = Path(directory) / "times.txt"
            times.write_text("100\n100\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_image_frames(times)


if __name__ == "__main__":
    unittest.main()
