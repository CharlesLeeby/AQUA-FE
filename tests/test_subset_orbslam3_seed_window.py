from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subset_orbslam3_seed_window.py"


class SubsetOrbSlam3SeedWindowTest(unittest.TestCase):
    def test_subsets_times_and_both_seed_files_by_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            times = root / "times.txt"
            full = root / "full.txt"
            drop = root / "drop.txt"
            output = root / "output"
            times.write_text("10\n20\n30\n40\n50\n", encoding="ascii")
            full.write_text(
                "# timestamp x y lineage quality\n"
                "10 1 2 7 0.9\n"
                "30 3 4 7 0.9\n"
                "50 5 6 7 0.9\n",
                encoding="ascii",
            )
            drop.write_text(
                "# timestamp x y lineage quality\n20 2 3 8 0.8\n",
                encoding="ascii",
            )

            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--image-times",
                    str(times),
                    "--full-seeds",
                    str(full),
                    "--drop-seeds",
                    str(drop),
                    "--first-frame",
                    "1",
                    "--last-frame",
                    "3",
                    "--output-dir",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual((output / "cam0_times.txt").read_text(), "20\n30\n40\n")
            self.assertEqual(
                (output / "full_seeds.txt").read_text(),
                "# timestamp x y lineage quality\n30 3 4 7 0.9\n",
            )
            self.assertEqual(
                (output / "drop_seeds.txt").read_text(),
                "# timestamp x y lineage quality\n20 2 3 8 0.8\n",
            )
            manifest = json.loads((output / "subset_manifest.json").read_text())
            self.assertEqual(manifest["selected_frames"], 3)
            self.assertEqual(manifest["selected_full_seed_rows"], 1)
            self.assertEqual(manifest["selected_drop_seed_rows"], 1)
            self.assertEqual(set(manifest["outputs"]), {
                "cam0_times.txt",
                "full_seeds.txt",
                "drop_seeds.txt",
            })

    def test_refuses_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name in ("times.txt", "full.txt", "drop.txt"):
                (root / name).write_text("10\n", encoding="ascii")
            output = root / "output"
            output.mkdir()

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--image-times",
                    str(root / "times.txt"),
                    "--full-seeds",
                    str(root / "full.txt"),
                    "--drop-seeds",
                    str(root / "drop.txt"),
                    "--first-frame",
                    "0",
                    "--last-frame",
                    "0",
                    "--output-dir",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing existing output directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
