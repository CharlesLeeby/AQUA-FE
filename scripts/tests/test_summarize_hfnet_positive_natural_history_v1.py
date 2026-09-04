#!/usr/bin/env python3
"""Process-free tests for the strict three-window HFNet runability summary."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "summarize_hfnet_positive_natural_history_v1.py"
SPEC = importlib.util.spec_from_file_location("hfnet_positive_natural_history_v1", str(SCRIPT))
assert SPEC is not None and SPEC.loader is not None
summary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = summary
SPEC.loader.exec_module(summary)


def identity(path: Path) -> dict:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def write_synthetic_a09(path: Path, *, corrupt_score: bool = False) -> None:
    attempt = path.parent
    result_dir = attempt / "result"
    result_dir.mkdir(parents=True)
    trajectory = result_dir / "trajectory.txt"
    keyframes = result_dir / "trajectory_keyframe.txt"
    crop = result_dir / "trajectory_score_4000_4400.txt"
    claim = attempt / "process_start_claim.json"
    trajectory.write_text("synthetic full trajectory\n", encoding="utf-8")
    keyframes.write_text("synthetic keyframes\n", encoding="utf-8")
    crop.write_text("synthetic score crop\n", encoding="utf-8")
    claim.write_text('{"synthetic":"one-shot claim"}\n', encoding="utf-8")
    init_ids = [0, 500, 1200, 2600, 3900]
    resets = [
        {"init_frame_id": init_ids[index], "next_first_frame_id": init_ids[index] + 10}
        for index in range(len(init_ids) - 1)
    ]
    result = {
        "schema_version": "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-result-v1",
        "status": "PASS_DEVELOPMENT_RUNABILITY_RESCUE",
        "claim_boundary": {
            "development_only": True,
            "accuracy_evaluated": False,
            "formal_paper_claim_authorized": False,
            "superiority_claimed": False,
            "fair_head_to_head": False,
        },
        "execution": {
            "popen_invocations": 1,
            "raw_returncode": 0,
            "retry_performed": False,
            "retry_permitted": False,
            "timed_out": False,
        },
        "failure_codes": [],
        "pins": {"process_start_claim": identity(claim)},
        "selection": {
            "sequence": "AQUALOC archaeology_sequence_9",
            "development_result_conditioned_selection": True,
            "feed_camera_count": 4401,
            "feed_source_frame_indices_inclusive": [0, 4400],
            "score_camera_count": 401,
            "score_source_frame_indices_inclusive": [4000, 4400],
            "history": "warm_start_at_natural_sequence_frame_0; no reset at score frame 4000",
        },
        "score_adjudication": {
            "passed": True,
            "failure_codes": [],
            "feed": {"indices_inclusive": [0, 4400], "camera_count": 4401},
            "score": {
                "indices_inclusive": [4000, 4400],
                "camera_count": 401,
                "pose_count": 400 if corrupt_score else 401,
                "first_index": 4000,
                "last_index": 4400,
                "exact_401_of_401_contiguous": True,
                "keyframe_count": 31,
                "preroll_to_score_boundary_continuous": True,
                "trajectory_crop": identity(crop),
            },
            "full_trajectory": {"valid": True, "pose_count": 500, "errors": []},
            "keyframes": {"valid": True, "pose_count": 40, "errors": []},
            "runtime_log": {
                "valid": True,
                "init_frame_ids": init_ids,
                "reset_events": resets,
                "pre_score_initialized": True,
                "score_window_init_frame_ids": [],
                "score_window_reset_events": [],
                "unresolved_reset_events": [],
                "reset_parse_complete": True,
            },
        },
        "support": {
            "trajectory": {
                "exists": True, "valid": True, "pose_count": 500,
                "errors": [], "identity": identity(trajectory),
            },
            "keyframes": {
                "exists": True, "valid": True, "pose_count": 40,
                "errors": [], "identity": identity(keyframes),
            },
        },
        "terminal_contract": {
            "attempt_consumed": True,
            "retry_after_pass_or_fail": False,
            "terminal_json_o_excl": True,
        },
        "watchdog": {"triggered": False, "child_reaped": True},
    }
    path.write_text(json.dumps(result), encoding="utf-8")


class HfnetPositiveNaturalHistoryV1Tests(unittest.TestCase):
    def test_a10_top_level_pass_with_false_adjudication_is_rejected(self) -> None:
        value = json.loads(summary.A10_RESULT.read_text(encoding="utf-8"))
        value["score_adjudication"]["passed"] = False
        with self.assertRaisesRegex(
            summary.EvidenceError, "A10_STATUS_ADJUDICATION_DISAGREEMENT"
        ):
            summary._validate_warm(summary.default_specs()[1], value)

    def test_a10_top_level_fail_with_true_adjudication_is_rejected(self) -> None:
        value = json.loads(summary.A10_RESULT.read_text(encoding="utf-8"))
        value["status"] = "FAIL_DEVELOPMENT_RUNABILITY_RESCUE"
        with self.assertRaisesRegex(
            summary.EvidenceError, "A10_STATUS_ADJUDICATION_DISAGREEMENT"
        ):
            summary._validate_warm(summary.default_specs()[1], value)

    def test_current_workspace_preterminal_validates_without_publishing(self) -> None:
        value = summary.build_summary(
            summary.default_specs(), summary.COLD_RESULTS,
            allow_preterminal=True, prepared_a09=summary.A09_PREPARED,
            generated_at="2026-08-25T00:00:00+00:00",
        )
        self.assertEqual(value["analysis_state"], "PRETERMINAL_VALIDATED_NOT_PUBLISHABLE")
        self.assertEqual([row["window_id"] for row in value["natural_history_windows"]], ["A06", "A10"])
        self.assertEqual(value["pending_window"]["window_id"], "A09")
        self.assertFalse(value["pending_window"]["publishable"])
        self.assertIsNone(value["descriptive_counts"]["runability_pass_count"])
        a06, a10 = value["natural_history_windows"]
        self.assertEqual(a06["history_events"]["init_frame_ids"], [0])
        self.assertEqual(a06["support"]["score_pose_count"], 251)
        self.assertEqual(a10["support"]["score_pose_count"], 401)
        self.assertEqual(a10["history_events"]["score_window_reset_count"], 0)
        for row in value["cold_start_history_sensitivity_diagnostics"]:
            self.assertIsNone(row["accuracy"]["value"])

    def test_publish_refuses_preterminal_before_creating_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "summary.json"
            markdown_path = root / "summary.md"
            with self.assertRaisesRegex(summary.EvidenceError, "PUBLISH_REFUSED_A09_NOT_TERMINAL"):
                value = summary.build_summary(
                    summary.default_specs(), summary.COLD_RESULTS,
                    allow_preterminal=False, prepared_a09=summary.A09_PREPARED,
                    generated_at="2026-08-25T00:00:00+00:00",
                )
                summary.publish(value, json_path, markdown_path)
            self.assertFalse(json_path.exists())
            self.assertFalse(markdown_path.exists())

    def test_terminal_three_window_bundle_publishes_null_accuracy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a09 = root / "a09/attempt_001/run_result.json"
            write_synthetic_a09(a09)
            specs = summary.default_specs(a09=a09)
            value = summary.build_summary(
                specs, summary.COLD_RESULTS, allow_preterminal=False,
                prepared_a09=root / "unused-prepared.json",
                generated_at="2026-08-25T00:00:00+00:00",
            )
            self.assertEqual(value["analysis_state"], "TERMINAL_DEVELOPMENT_ONLY")
            self.assertEqual(value["descriptive_counts"]["runability_pass_count"], 3)
            self.assertEqual([row["window_id"] for row in value["natural_history_windows"]],
                             ["A06", "A10", "A09"])
            json_path = root / "published/summary.json"
            markdown_path = root / "published/summary.md"
            summary.publish(value, json_path, markdown_path)
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            for row in loaded["natural_history_windows"]:
                self.assertEqual(row["accuracy"]["state"], "NOT_EVALUATED")
                self.assertIsNone(row["accuracy"]["value"])
            text = markdown_path.read_text(encoding="utf-8")
            self.assertIn("精度均为 NA", text)
            self.assertIn("历史敏感性诊断", text)
            self.assertNotIn("APE", text)
            self.assertNotIn("RPE", text)
            with self.assertRaisesRegex(summary.EvidenceError, "MARKDOWN_OUTPUT_EXISTS"):
                summary.publish(value, root / "published/second.json", markdown_path)

    def test_terminal_score_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            a09 = Path(directory) / "a09/attempt_001/run_result.json"
            write_synthetic_a09(a09, corrupt_score=True)
            with self.assertRaisesRegex(summary.EvidenceError, "A09_SCORE_POSES"):
                summary.build_summary(
                    summary.default_specs(a09=a09), summary.COLD_RESULTS,
                    allow_preterminal=False, prepared_a09=Path(directory) / "unused.json",
                )

    def test_preterminal_claim_contradiction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "attempt_001/run_result.json"
            prepared = root / "attempt_001/prepared_manifest.json"
            prepared.parent.mkdir(parents=True)
            frozen = json.loads(summary.A09_PREPARED.read_text(encoding="utf-8"))
            prepared.write_text(json.dumps(frozen), encoding="utf-8")
            (prepared.parent / "process_start_claim.json").write_text("{}\n", encoding="utf-8")
            spec = summary.default_specs(a09=result)[2]
            with self.assertRaisesRegex(summary.EvidenceError, "START_CLAIM"):
                summary.validate_prepared_a09(prepared, spec)

    def test_source_has_no_process_execution_surface(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        forbidden = ("import subprocess", "from subprocess", "Popen(", "os.system(",
                     "os.kill(", "psutil", "shell=True")
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
