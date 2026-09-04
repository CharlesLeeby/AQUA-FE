from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_orbslam3_seeded_runs import (
    INSTRUMENTATION_SUMMARY_FIELDS,
    instrumentation_aware_status,
    instrumentation_summary,
    main,
)


def complete_summary(output_directory: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "complete": True,
        "loaded_seed_observations": 30,
        "attempted_seed_observations": 30,
        "accepted_seed_observations": 28,
        "seed_lineages_loaded": 2,
        "seed_lineages_accepted": 2,
        "seed_lineages_with_mappoint": 1,
        "seed_lineages_surviving": 1,
        "accepted_observations_with_mappoint": 17,
        "distinct_mappoints": 3,
        "keyframe_observations": 8,
        "distinct_keyframes": 4,
        "mappoint_observations_median": 3.5,
        "mappoint_observations_max": 7,
        "mappoint_found_ratio_median": 0.75,
        "max_covisibility_weight": None,
        "status": "ok",
        "output_directory": str(output_directory.resolve()),
        "event_capacity": 1000,
        "events_recorded": 90,
        "events_overflowed": 0,
        "related_mappoint_capacity": 100,
        "related_mappoint_overflowed": 0,
        "loaded_seed_rows": 30,
        "phase_attempted": 30,
        "phase_skipped": 0,
        "extractor_accepted": 28,
        "extractor_rejected_border": 2,
        "extractor_rejected_native_duplicate": 0,
        "extractor_rejected_seed_duplicate": 0,
        "frame_accepted": 28,
        "raw_association_events": 17,
        "frame_final": 28,
        "related_mappoints": 3,
        "lineages": 2,
        "phase_conservation": True,
        "extractor_conservation": True,
        "accepted_conservation": True,
        "valid_tokens": True,
        "mappoint_pointer_consistency": True,
        "per_token_conservation": True,
        "mappoint_pointer_key_consistency": True,
        "atlas_snapshot_available": True,
    }


class OrbSlam3SeededEvaluatorInstrumentationTest(unittest.TestCase):
    def test_missing_legacy_summary_stays_blank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = instrumentation_summary(Path(directory))

        self.assertEqual(set(values), set(INSTRUMENTATION_SUMMARY_FIELDS))
        self.assertTrue(all(value == "" for value in values.values()))

    def test_partial_instrumentation_directory_is_incomplete_not_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "instrumentation").mkdir()

            values = instrumentation_summary(run_dir)

        self.assertEqual(values["complete"], 0)
        self.assertEqual(values["schema_version"], "")
        self.assertEqual(
            instrumentation_aware_status("ok", values),
            "instrumentation_incomplete",
        )

    def test_loads_complete_summary_and_preserves_null_as_blank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir()
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(complete_summary(instrumentation)), encoding="utf-8"
            )

            values = instrumentation_summary(run_dir, require_instrumentation=True)

        self.assertEqual(values["schema_version"], 1)
        self.assertEqual(values["complete"], 1)
        self.assertEqual(values["accepted_seed_observations"], 28)
        self.assertEqual(values["max_covisibility_weight"], "")
        self.assertEqual(values["instrumentation_overflowed"], 0)
        self.assertEqual(values["instrumentation_conservation_ok"], 1)

    def test_required_summary_rejects_missing_or_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            with self.assertRaisesRegex(SystemExit, "missing required"):
                instrumentation_summary(run_dir, require_instrumentation=True)

            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir()
            summary = complete_summary(instrumentation)
            summary["complete"] = False
            summary["status"] = "invalid"
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            with self.assertRaisesRegex(SystemExit, "incomplete required"):
                instrumentation_summary(run_dir, require_instrumentation=True)

    def test_rejects_wrong_schema_and_invalid_numeric_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir()
            summary_path = instrumentation / "seed_summary.json"

            wrong_schema = complete_summary(instrumentation)
            wrong_schema["schema_version"] = 2
            summary_path.write_text(json.dumps(wrong_schema), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version"):
                instrumentation_summary(run_dir)

            invalid_count = complete_summary(instrumentation)
            invalid_count["attempted_seed_observations"] = -1
            summary_path.write_text(json.dumps(invalid_count), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                instrumentation_summary(run_dir)

    def test_legacy_main_appends_blank_instrumentation_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs_root = root / "runs"
            run_dir = runs_root / "orb_only_r1"
            run_dir.mkdir(parents=True)
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=0 attempted=0 accepted=0\n",
                encoding="utf-8",
            )
            image_times = root / "times.txt"
            image_times.write_text("1000000000\n2000000000\n", encoding="ascii")
            gt = root / "gt.txt"
            gt.write_text("", encoding="ascii")
            output = root / "runs.csv"
            argv = [
                "evaluate_orbslam3_seeded_runs.py",
                "--runs-root",
                str(runs_root),
                "--gt-tum",
                str(gt),
                "--image-times",
                str(image_times),
                "--max-time-diff",
                "0.01",
                "--rpe-delta-frames",
                "1",
                "--output-csv",
                str(output),
            ]

            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(main(), 0)
            with output.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["status"], "empty_trajectory")
        for field in INSTRUMENTATION_SUMMARY_FIELDS:
            self.assertEqual(row[field], "")

    def test_online_kind_uses_online_trajectory_and_separate_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs_root = root / "runs"
            run_dir = runs_root / "orb_only_r1"
            run_dir.mkdir(parents=True)
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=0 attempted=0 accepted=0\n",
                encoding="utf-8",
            )
            (run_dir / "f_fixture.txt").write_text(
                "1000000000 0 0 0 0 0 0 1\n"
                "2000000000 1 0 0 0 0 0 1\n",
                encoding="ascii",
            )
            (run_dir / "online_f_fixture.txt").write_text(
                "1000000000 0 0 0 0 0 0 1\n",
                encoding="ascii",
            )
            image_times = root / "times.txt"
            image_times.write_text(
                "1000000000\n2000000000\n", encoding="ascii"
            )
            gt = root / "gt.txt"
            gt.write_text("", encoding="ascii")
            output = root / "online.csv"
            argv = [
                "evaluate_orbslam3_seeded_runs.py",
                "--runs-root",
                str(runs_root),
                "--gt-tum",
                str(gt),
                "--image-times",
                str(image_times),
                "--max-time-diff",
                "0.01",
                "--rpe-delta-frames",
                "1",
                "--trajectory-kind",
                "online",
                "--output-csv",
                str(output),
            ]

            def fake_run_evo(command: list[str], report: Path) -> None:
                report.write_text(
                    "rmse 0.1\nmedian 0.08\nmax 0.2\n", encoding="utf-8"
                )

            with mock.patch.object(sys, "argv", argv), mock.patch(
                "evaluate_orbslam3_seeded_runs.run_evo", side_effect=fake_run_evo
            ):
                self.assertEqual(main(), 0)
            with output.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["trajectory_kind"], "online")
            self.assertEqual(row["output_poses"], "1")
            self.assertTrue((run_dir / "online_ape_trans.txt").is_file())
            self.assertTrue((run_dir / "online_rpe_trans_1f.txt").is_file())
            self.assertTrue((run_dir / "online_f_fixture_sec.txt").is_file())
            self.assertFalse((run_dir / "f_fixture_sec.txt").exists())

    def test_non_strict_incomplete_instrumentation_cannot_report_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs_root = root / "runs"
            run_dir = runs_root / "full_r1"
            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir(parents=True)
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=2 attempted=30 accepted=28\n",
                encoding="utf-8",
            )
            summary = complete_summary(instrumentation)
            summary["complete"] = False
            summary["status"] = "invalid"
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            (run_dir / "f_fixture.txt").write_text(
                "1000000000 0 0 0 0 0 0 1\n"
                "2000000000 1 0 0 0 0 0 1\n",
                encoding="ascii",
            )
            image_times = root / "times.txt"
            image_times.write_text(
                "1000000000\n2000000000\n", encoding="ascii"
            )
            gt = root / "gt.txt"
            gt.write_text("", encoding="ascii")
            output = root / "runs.csv"
            argv = [
                "evaluate_orbslam3_seeded_runs.py",
                "--runs-root",
                str(runs_root),
                "--gt-tum",
                str(gt),
                "--image-times",
                str(image_times),
                "--max-time-diff",
                "0.01",
                "--rpe-delta-frames",
                "1",
                "--output-csv",
                str(output),
            ]

            def fake_run_evo(command: list[str], report: Path) -> None:
                report.write_text(
                    "rmse 0.1\nmedian 0.08\nmax 0.2\n", encoding="utf-8"
                )

            with mock.patch.object(sys, "argv", argv), mock.patch(
                "evaluate_orbslam3_seeded_runs.run_evo", side_effect=fake_run_evo
            ):
                self.assertEqual(main(), 0)
            with output.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["status"], "instrumentation_incomplete")
        self.assertEqual(row["instrumentation_overflowed"], "0")
        self.assertEqual(row["instrumentation_conservation_ok"], "1")

    def test_main_rejects_log_counter_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs_root = root / "runs"
            run_dir = runs_root / "full_r1"
            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir(parents=True)
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=2 attempted=29 accepted=28\n",
                encoding="utf-8",
            )
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(complete_summary(instrumentation)), encoding="utf-8"
            )
            image_times = root / "times.txt"
            image_times.write_text("1000000000\n", encoding="ascii")
            gt = root / "gt.txt"
            gt.write_text("", encoding="ascii")
            output = root / "runs.csv"
            argv = [
                "evaluate_orbslam3_seeded_runs.py",
                "--runs-root",
                str(runs_root),
                "--gt-tum",
                str(gt),
                "--image-times",
                str(image_times),
                "--max-time-diff",
                "0.01",
                "--rpe-delta-frames",
                "1",
                "--output-csv",
                str(output),
            ]

            with mock.patch.object(sys, "argv", argv), self.assertRaisesRegex(
                ValueError, "attempted count mismatch"
            ):
                main()

    def test_orb_only_instrumentation_rejects_loaded_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs_root = root / "runs"
            run_dir = runs_root / "orb_only_r1"
            instrumentation = run_dir / "instrumentation"
            instrumentation.mkdir(parents=True)
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=2 attempted=30 accepted=28\n",
                encoding="utf-8",
            )
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(complete_summary(instrumentation)), encoding="utf-8"
            )
            image_times = root / "times.txt"
            image_times.write_text("1000000000\n", encoding="ascii")
            gt = root / "gt.txt"
            gt.write_text("", encoding="ascii")
            output = root / "runs.csv"
            argv = [
                "evaluate_orbslam3_seeded_runs.py",
                "--runs-root",
                str(runs_root),
                "--gt-tum",
                str(gt),
                "--image-times",
                str(image_times),
                "--max-time-diff",
                "0.01",
                "--rpe-delta-frames",
                "1",
                "--output-csv",
                str(output),
            ]

            with mock.patch.object(sys, "argv", argv), self.assertRaisesRegex(
                ValueError, "loaded_seed_observations must be zero"
            ):
                main()


if __name__ == "__main__":
    unittest.main()
