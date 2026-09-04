from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import audit_p07_frontend_export_v4 as audit


ATTEMPT = Path(
    "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
    "queue_028_isj_p07_afrl_bus_outside_0001_b1_attempt01"
)
RUN_DIR = Path(
    "logs/afrl_cave_v31/"
    "external_klt_every2_isj_p07_afrl_bus_outside_0001_b1_attempt01"
)


class P07AfrlAuditorCorrectionV4Tests(unittest.TestCase):
    def test_preserved_queue28_passes_metadata_aware_audit(self) -> None:
        payload = audit.build_audit(
            index=28,
            command_log=ATTEMPT / "command.log",
            attestation=RUN_DIR / "features.bag.quality-contract.json",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["feature_bag"]["feature_frames"], 283)
        self.assertTrue(payload["checks"]["afrl_replay_manifest_metadata_only"])
        self.assertFalse(payload["held_out_trajectory_outcome_read"])

    def test_existing_vio_is_never_classified_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "vins_output").mkdir()
            for name in (
                "cave_gennie_short.bag",
                "features.bag",
                "vins_afrl_cave_external.yaml",
            ):
                (run_dir / name).write_bytes(b"x")
            (run_dir / "vins_output/vio.csv").write_text("outcome\n", encoding="utf-8")
            values = {
                "run_dir": str(run_dir),
                "short_bag": str(run_dir / "cave_gennie_short.bag"),
                "play_bag": str(run_dir / "features.bag"),
                "feature_bag": str(run_dir / "features.bag"),
                "vins_config": str(run_dir / "vins_afrl_cave_external.yaml"),
                "vins_csv": str(run_dir / "vins_output/vio.csv"),
            }
            (run_dir / "replay_manifest.txt").write_text(
                "".join(f"{key}={value}\n" for key, value in values.items()),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(audit.AuditViolation, "trajectory outcome"):
                audit.validate_metadata_manifest(run_dir)


if __name__ == "__main__":
    unittest.main()
