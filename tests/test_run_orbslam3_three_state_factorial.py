from __future__ import annotations

import csv
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_orbslam3_three_state_factorial.sh"


class OrbSlam3ThreeStateFactorialTest(unittest.TestCase):
    def test_interleaves_all_states_and_records_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            preaudit = root / "preaudit"
            current = root / "current"
            for orb_root in (preaudit, current):
                binary = orb_root / "Examples_old" / "Monocular" / "mono_euroc_old"
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/usr/bin/env bash\n", encoding="ascii")
                binary.chmod(0o755)

            calls = root / "calls.csv"
            fake_triplet = root / "fake_triplet.sh"
            fake_triplet.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s,%s,%s,%s,%s\\n' \"$ORB_ROOT\" "
                "\"$ORB_SLAM3_ENABLE_SEED_AUDIT\" \"$ORB_SLAM3_ROLE_ORDER\" "
                "\"$6\" \"$8\" >> \"$FACTORIAL_CALLS\"\n",
                encoding="ascii",
            )
            fake_triplet.chmod(0o755)

            dataset = root / "dataset"
            dataset.mkdir()
            inputs = []
            for name in ("times.txt", "config.yaml", "full.txt", "drop.txt"):
                path = root / name
                path.write_text("fixture\n", encoding="ascii")
                inputs.append(path)
            output = root / "output"

            env = os.environ.copy()
            env["TRIPLET_RUNNER"] = str(fake_triplet)
            env["FACTORIAL_CALLS"] = str(calls)
            subprocess.run(
                [
                    "bash",
                    str(RUNNER),
                    str(dataset),
                    *(str(path) for path in inputs),
                    str(output),
                    "fixture",
                    str(preaudit),
                    str(current),
                ],
                check=True,
                env=env,
                text=True,
                capture_output=True,
            )

            with calls.open() as handle:
                call_rows = list(csv.reader(handle))
            self.assertEqual(len(call_rows), 24)
            self.assertEqual(
                {row[1] for row in call_rows},
                {"0", "1"},
            )
            self.assertEqual(
                sum(row[1] == "1" for row in call_rows),
                8,
            )
            self.assertEqual(
                {Path(row[3]).name for row in call_rows},
                {"preaudit_reconstructed", "current_audit_off", "current_audit_on"},
            )
            with (output / "three_state_schedule.csv").open() as handle:
                schedule = list(csv.DictReader(handle))
            self.assertEqual(len(schedule), 8)
            for row in schedule:
                self.assertEqual(
                    set(row["state_order"].split()),
                    {"preaudit_reconstructed", "current_audit_off", "current_audit_on"},
                )
                self.assertEqual(
                    set(row["role_order"].split()),
                    {"orb_only", "drop", "full"},
                )


if __name__ == "__main__":
    unittest.main()
