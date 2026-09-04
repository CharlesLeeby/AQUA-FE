from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compose_orbslam3_preroll_dataset.py"


def make_dataset(root: Path, times: list[int]) -> None:
    image_dir = root / "mav0/cam0/data"
    imu_dir = root / "mav0/imu0"
    gt_dir = root / "mav0/state_groundtruth_estimate0"
    image_dir.mkdir(parents=True)
    imu_dir.mkdir(parents=True)
    gt_dir.mkdir(parents=True)
    (root / "cam0_times.txt").write_text(
        "".join(f"{stamp}\n" for stamp in times), encoding="ascii"
    )
    for stamp in times:
        (image_dir / f"{stamp}.png").write_bytes(f"image-{stamp}".encode("ascii"))
    with (imu_dir / "data.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["#timestamp [ns]", "wx"])
        writer.writerows((stamp, "0.1") for stamp in times)
    with (gt_dir / "data.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["#timestamp", "px"])
        writer.writerows((stamp, str(stamp)) for stamp in times)
    (root / "groundtruth_tum.txt").write_text(
        "".join(
            f"{stamp * 1e-9:.9f} {stamp} 0 0 0 0 0 1\n" for stamp in times
        ),
        encoding="ascii",
    )


class ComposeOrbSlam3PrerollDatasetTest(unittest.TestCase):
    def test_prepends_only_frames_strictly_before_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix = root / "prefix"
            suffix = root / "suffix"
            output = root / "output"
            make_dataset(prefix, [10, 20, 30, 40])
            make_dataset(suffix, [40, 50, 60])

            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--prefix-dataset",
                    str(prefix),
                    "--suffix-dataset",
                    str(suffix),
                    "--prefix-frames",
                    "2",
                    "--output-dir",
                    str(output),
                    "--imu-margin-ns",
                    "0",
                    "--gt-margin-ns",
                    "0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                (output / "cam0_times.txt").read_text(encoding="ascii"),
                "20\n30\n40\n50\n60\n",
            )
            self.assertEqual(
                sorted(path.name for path in (output / "mav0/cam0/data").iterdir()),
                ["20.png", "30.png", "40.png", "50.png", "60.png"],
            )
            manifest = json.loads((output / "export_metadata.json").read_text())
            self.assertEqual(manifest["prefix_frames_selected"], 2)
            self.assertEqual(manifest["suffix_frames"], 3)
            self.assertTrue(manifest["suffix_times_exact"])
            self.assertTrue(manifest["suffix_images_exact"])

    def test_refuses_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix = root / "prefix"
            suffix = root / "suffix"
            output = root / "output"
            make_dataset(prefix, [10, 20])
            make_dataset(suffix, [30, 40])
            output.mkdir()
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--prefix-dataset",
                    str(prefix),
                    "--suffix-dataset",
                    str(suffix),
                    "--prefix-frames",
                    "1",
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
