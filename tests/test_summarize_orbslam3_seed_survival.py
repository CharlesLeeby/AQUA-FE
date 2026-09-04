from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from summarize_orbslam3_seed_survival import evaluator_wins, load_group


class SummarizeOrbSlam3SeedSurvivalTest(unittest.TestCase):
    def _write_evaluator(
        self, root: Path, repeats: range, include_bridge_off: bool = True
    ) -> Path:
        roles = ["orb_only", "drop", "full"]
        if include_bridge_off:
            roles.insert(2, "full_bridge_off")
        rows = []
        metrics = {
            "orb_only": (0.0062, 0.0118),
            "drop": (0.0062, 0.0118),
            "full_bridge_off": (0.0088, 0.0164),
            "full": (0.0057, 0.0092),
        }
        for repeat in repeats:
            for role in roles:
                run_dir = root / f"{role}_r{repeat}"
                run_dir.mkdir()
                ape, rpe = metrics[role]
                rows.append(
                    {
                        "role": role,
                        "repeat": repeat,
                        "run_dir": str(run_dir),
                        "coverage_ratio": 0.85,
                        "ape_rmse_m": ape,
                        "rpe_rmse_m": rpe,
                    }
                )
        path = root / "runs.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_evaluator_wins_accepts_three_repeat_four_arm_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_evaluator(root, range(1, 4))
            wins = evaluator_wins(path, root)

        self.assertEqual(wins["full_vs_orb_pairs"], 3)
        self.assertEqual(wins["full_vs_orb_double_wins"], 3)
        self.assertEqual(wins["full_vs_drop_pairs"], 3)
        self.assertEqual(wins["full_vs_drop_double_wins"], 3)
        self.assertEqual(wins["full_vs_bridge_off_pairs"], 3)
        self.assertEqual(wins["full_vs_bridge_off_double_wins"], 3)

    def test_evaluator_wins_rejects_incomplete_optional_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_evaluator(root, range(1, 4))
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows = [
                row
                for row in rows
                if not (row["role"] == "full_bridge_off" and row["repeat"] == "3")
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(SystemExit, "incomplete evaluator matrix"):
                evaluator_wins(path, root)

    def test_loads_complete_survival_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrumentation = root / "full_r1" / "instrumentation"
            instrumentation.mkdir(parents=True)
            summary = {
                "schema_version": 1,
                "complete": True,
                "status": "ok",
                "output_directory": str(instrumentation),
                "events_overflowed": 0,
                "related_mappoint_overflowed": 0,
                "loaded_seed_observations": 2,
                "attempted_seed_observations": 2,
                "accepted_seed_observations": 2,
                "seed_lineages_loaded": 2,
                "seed_lineages_accepted": 2,
                "seed_lineages_with_mappoint": 1,
                "seed_lineages_surviving": 1,
                "accepted_observations_with_mappoint": 1,
                "distinct_mappoints": 1,
                "keyframe_observations": 1,
                "distinct_keyframes": 1,
                "events_recorded": 8,
                "phase_attempted": 2,
                "phase_skipped": 0,
                "extractor_accepted": 2,
                "extractor_rejected_border": 0,
                "extractor_rejected_native_duplicate": 0,
                "extractor_rejected_seed_duplicate": 0,
                "frame_accepted": 2,
                "raw_association_events": 0,
                "frame_final": 2,
                "related_mappoints": 1,
                "lineages": 2,
                "phase_conservation": True,
                "extractor_conservation": True,
                "accepted_conservation": True,
                "per_token_conservation": True,
                "valid_tokens": True,
                "mappoint_pointer_consistency": True,
                "mappoint_pointer_key_consistency": True,
                "atlas_snapshot_available": True,
            }
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            (instrumentation / "seed_events.csv").write_text(
                "event,lineage_id,map_id,mp_id\n"
                "phase_attempted,7,,\nphase_attempted,8,,\n"
                "extract_accepted,7,,\nextract_accepted,8,,\n"
                "frame_accepted,7,,\nframe_accepted,8,,\n"
                "frame_final,7,,\nframe_final,8,,\n",
                encoding="ascii",
            )
            (instrumentation / "seed_lineages.csv").write_text(
                "lineage_id,input_observations,attempted,phase_skipped,accepted,"
                "unique_mappoints,live_mappoints\n"
                "7,1,1,0,1,1,1\n8,1,1,0,1,0,0\n",
                encoding="ascii",
            )
            (instrumentation / "seed_mappoint_summary.csv").write_text(
                "map_id,mp_id,all_lineages,surviving,final_observations,max_observations,raw_frame_matches,frame_matches,"
                "seed_kf_observations,seed_match_frame_span,seed_match_duration_s,"
                "found_ratio,final_kf_observers,historical_kf_observers,"
                "covisibility_pairs,covisibility_weight_sum,covisibility_weight_max\n"
                "0,1,7,1,4,6,5,5,1,8,0.4,0.5,4,1,6,20,9\n",
                encoding="ascii",
            )
            (root / "full_r1" / "run_manifest.txt").write_text(
                "role=full\nrepeat=1\nseed_audit_enabled=1\nseed_file=/tmp/seeds.txt\n"
                "seed_sha256=abc\nseed_audit_dir=" + str(instrumentation) + "\n",
                encoding="utf-8",
            )

            per_run, per_lineage, per_mappoint = load_group("case", root)
            summary["seed_lineages_loaded"] = 3
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            with self.assertRaisesRegex(SystemExit, "lineage row count disagrees"):
                load_group("case", root)

        self.assertEqual(len(per_run), 1)
        self.assertEqual(len(per_lineage), 2)
        self.assertEqual(len(per_mappoint), 1)
        self.assertEqual(per_run.iloc[0]["lineage_to_mappoint_rate"], 0.5)
        self.assertEqual(
            per_run.iloc[0]["lineage_with_mappoint_survival_rate"], 1.0
        )
        self.assertEqual(per_run.iloc[0]["mappoint_final_observations_median"], 4.0)
        self.assertEqual(per_run.iloc[0]["raw_association_hook_complete"], 0)

    def test_rejects_failed_integrity_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrumentation = root / "full_r1" / "instrumentation"
            instrumentation.mkdir(parents=True)
            summary = {
                "schema_version": 1,
                "complete": True,
                "status": "ok",
                "output_directory": str(instrumentation),
                "events_overflowed": 0,
                "related_mappoint_overflowed": 0,
                **{
                    field: True
                    for field in (
                        "phase_conservation",
                        "extractor_conservation",
                        "accepted_conservation",
                        "per_token_conservation",
                        "valid_tokens",
                        "mappoint_pointer_consistency",
                        "mappoint_pointer_key_consistency",
                        "atlas_snapshot_available",
                    )
                },
            }
            summary["per_token_conservation"] = False
            (instrumentation / "seed_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            for name in ("seed_events.csv", "seed_lineages.csv", "seed_mappoint_summary.csv"):
                (instrumentation / name).write_text("header\n", encoding="ascii")
            with self.assertRaisesRegex(SystemExit, "integrity fields failed"):
                load_group("case", root)


if __name__ == "__main__":
    unittest.main()
