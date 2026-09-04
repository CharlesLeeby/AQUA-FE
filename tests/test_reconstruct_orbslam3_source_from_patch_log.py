from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reconstruct_orbslam3_source_from_patch_log import RecordedChange, reverse_changes


class ReconstructOrbSlam3SourceTest(unittest.TestCase):
    def test_reverses_updates_and_then_removes_recorded_addition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.txt").write_text("new\n", encoding="utf-8")
            (root / "added.txt").write_text("changed\n", encoding="utf-8")
            changes = [
                RecordedChange(
                    "2026-01-01T00:00:00Z",
                    0,
                    1,
                    0,
                    "added.txt",
                    "add",
                    None,
                    "base\n",
                    "add",
                    "session",
                ),
                RecordedChange(
                    "2026-01-01T00:00:01Z",
                    0,
                    2,
                    0,
                    "existing.txt",
                    "update",
                    "@@ -1 +1 @@\n-old\n+new\n",
                    None,
                    "update-existing",
                    "session",
                ),
                RecordedChange(
                    "2026-01-01T00:00:02Z",
                    0,
                    3,
                    0,
                    "added.txt",
                    "update",
                    "@@ -1 +1 @@\n-base\n+changed\n",
                    None,
                    "update-added",
                    "session",
                ),
            ]

            reverse_changes(root, changes)

            self.assertEqual((root / "existing.txt").read_text(), "old\n")
            self.assertFalse((root / "added.txt").exists())


if __name__ == "__main__":
    unittest.main()
