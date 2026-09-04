#!/usr/bin/env python3
"""Non-model tests for the A02 strict70 full-history HFNet controller."""

import importlib.util
import inspect
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "run_hfnet_v6_a02_0001_6300_score_4500_6300_strict70_v2.py"
)
SPEC = importlib.util.spec_from_file_location("hfnet_v6_a02_strict70_runner", str(RUNNER))
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def base_config() -> str:
    return "\n".join(
        (
            "%YAML:1.0",
            'Camera.type: "PinHole"',
            "Camera.width: 968",
            "Camera.height: 608",
            "Camera.fps: 20",
            "IMU.NoiseGyro: 0.003",
            "IMU.NoiseAcc: 0.05",
            "IMU.GyroWalk: 0.0001",
            "IMU.AccWalk: 0.0015",
            "IMU.Frequency: 200.0",
            'Extractor.type: "HFNetRT"',
            runner.BASE_MODEL_PATH_LINE,
            "Extractor.scaleFactor: 1.2",
            "Extractor.nLevels: 4",
            "Extractor.nFeatures: 675",
            "Extractor.threshold: 0.01",
            "loopClosing: 1",
            "",
        )
    )


def trajectory(count: int, longest: int, *, reported=None):
    coverage = count / float(runner.SCORE_CAMERA_COUNT) if reported is None else reported
    return {
        "valid": True,
        "overall": {"last_index": runner.SCORE_FIRST_INDEX + max(count - 1, 0)},
        "score": {
            "count": count,
            "coverage_fraction": coverage,
            "longest_contiguous_run": longest,
        },
    }


class A02Strict70RunnerTests(unittest.TestCase):
    def test_protocol_and_abandonment_pins_are_exact(self) -> None:
        self.assertEqual(
            runner.engine.content_identity(runner.REUSED_V1_CONTROLLER),
            runner.REUSED_V1_CONTROLLER_EXPECTED,
        )
        self.assertEqual(
            runner.engine.content_identity(runner.STRICT70_PROTOCOL),
            runner.STRICT70_PROTOCOL_EXPECTED,
        )
        self.assertEqual(
            runner.engine.content_identity(runner.V1_ABANDONMENT_RECEIPT),
            runner.V1_ABANDONMENT_RECEIPT_EXPECTED,
        )
        self.assertEqual(
            runner.engine.content_identity(runner.DEPENDENCY_V2_SUPERSESSION_RECEIPT),
            runner.DEPENDENCY_V2_SUPERSESSION_RECEIPT_EXPECTED,
        )
        for record in runner.ADOPTED_READ_ONLY.values():
            self.assertEqual(runner.engine.content_identity(record["path"]), {
                "size_bytes": record["size_bytes"],
                "sha256": record["sha256"],
            })

    def test_score_gate_is_exact_ceil_seventy_percent(self) -> None:
        self.assertEqual(runner.SCORE_CAMERA_COUNT, 1801)
        self.assertEqual(math.ceil(0.70 * runner.SCORE_CAMERA_COUNT), 1261)
        self.assertEqual(runner.MIN_SCORE_POSES, 1261)
        self.assertEqual(runner.MIN_CONTIGUOUS_SCORE_POSES, 1261)
        self.assertEqual((runner.SCORE_FIRST_INDEX, runner.SCORE_LAST_INDEX), (4499, 6299))

    def test_strict_gate_rejects_1260_and_accepts_1261(self) -> None:
        self.assertFalse(runner.strict70_trajectory_adjudication(trajectory(1260, 1260))["pass"])
        accepted = runner.strict70_trajectory_adjudication(trajectory(1261, 1261))
        self.assertTrue(accepted["pass"])
        self.assertGreaterEqual(accepted["score_coverage_fraction_derived"], 0.70)
        self.assertGreaterEqual(accepted["longest_contiguous_score_fraction"], 0.70)

    def test_strict_gate_requires_explicit_coverage_consistency(self) -> None:
        value = runner.strict70_trajectory_adjudication(trajectory(1261, 1261, reported=0.99))
        self.assertFalse(value["score_coverage_fraction_consistent"])
        self.assertFalse(value["pass"])

    def test_v2_producer_uses_6300_image_basis_and_own_seal(self) -> None:
        source = inspect.getsource(runner.run_strict70)
        self.assertIn("sequential 6300-image loop", source)
        self.assertNotIn("sequential 1801-image loop", source)
        self.assertIs(runner.engine.run, runner.run_strict70)

    def test_prepared_policy_splits_development_and_gate_knowledge(self) -> None:
        source = inspect.getsource(runner.prepare_strict70)
        self.assertIn('"result_conditioned_selection": True', source)
        self.assertIn('"experiment_and_window_selection_is_development_result_informed": True', source)
        self.assertIn('"strict70_threshold_correction_is_pre_v2_result_outcome_blind": True', source)
        self.assertIs(runner.engine.prepare, runner.prepare_strict70)

    def test_protocol_blocks_accuracy_head_to_head_for_history_mismatch(self) -> None:
        protocol = json.loads(runner.STRICT70_PROTOCOL.read_text(encoding="utf-8"))
        boundary = protocol["comparison_boundary"]
        self.assertEqual(boundary["external_hfnet_feed_history_source_indices_inclusive"], [1, 6300])
        self.assertEqual(
            boundary["existing_adopted_b1_constq_xfeatbirth_feed_history_source_indices_inclusive"],
            [4500, 6300],
        )
        self.assertEqual(boundary["possible_common_score_support_source_intersection_inclusive"], [5400, 6300])
        self.assertEqual(boundary["accuracy_head_to_head_status"], "BLOCKED_HISTORY_MISMATCH")
        self.assertFalse(boundary["fair_direct_accuracy_comparison_permitted"])
        self.assertIn("b1_constq", boundary["existing_adopted_evidence_family"].lower())

    def test_profile_references_the_adopted_5400_score_family_not_formal900(self) -> None:
        source = inspect.getsource(runner.collect_profile)
        self.assertIn("existing_adopted_b1_constq_vio", source)
        self.assertIn("existing_adopted_xfeatbirth_rawlk_vio", source)
        self.assertNotIn("formal900_r4", source)
        self.assertIn("preroll_b1_constq_vins_post_incident_v2_3_r1", str(
            runner.ADOPTED_READ_ONLY["b1_constq_vio"]["path"]
        ))
        self.assertIn("preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1", str(
            runner.ADOPTED_READ_ONLY["xfeatbirth_rawlk_vio"]["path"]
        ))

    def test_superseded_dependency_inventory_is_not_reused(self) -> None:
        self.assertTrue(runner.DEPENDENCY_INVENTORY.name.endswith("_v2_1.json"))
        self.assertNotEqual(
            runner.DEPENDENCY_INVENTORY,
            runner.ROOT / "papers/hfnet_v6_a02_0001_6300_dependency_inventory_v2.json",
        )

    def test_execution_lock_discloses_gate_and_history_mismatch(self) -> None:
        prepared = {
            "profile": {
                "preparation_and_stack": {
                    "identities": {
                        "reused_v1_controller": {"sha256": "v1"},
                        "strict70_v2_controller": {"sha256": "v2"},
                        "strict70_protocol": {"sha256": "protocol"},
                        "v1_abandonment_receipt": {"sha256": "abandoned"},
                        "dependency_v2_supersession_receipt": {"sha256": "superseded"},
                    },
                    "adopted_b1_constq_xfeatbirth_read_only_pins": {
                        "b1_constq_vio": {"sha256": "b1"},
                        "xfeatbirth_rawlk_vio": {"sha256": "xfeat"},
                    },
                    "v1_abandoned_live_absence": {
                        "status": "PASS_V1_REMAINS_PREPARED_ONLY_PRELOCK_UNSTARTED",
                        "all_forbidden_terminal_paths_absent": True,
                        "observations": {},
                    },
                }
            }
        }
        with mock.patch.object(runner, "_base_build_execution_lock", return_value={}):
            value = runner.build_execution_lock(
                runner.DEFAULT_SPEC, prepared, "2026-08-22T00:00:00+00:00"
            )
        self.assertEqual(value["strict70_primary_gate"]["minimum_score_poses"], 1261)
        self.assertEqual(
            value["strict70_primary_gate"]["minimum_contiguous_score_poses"], 1261
        )
        self.assertEqual(
            value["comparison_window_boundary"]["accuracy_head_to_head_status"],
            "BLOCKED_HISTORY_MISMATCH",
        )
        self.assertFalse(
            value["comparison_window_boundary"]["fair_direct_accuracy_comparison_permitted"]
        )

    def test_runtime_config_changes_model_path_only(self) -> None:
        target = Path("/tmp/a02 strict70/HFNet-RT")
        before = base_config()
        after = runner.derive_runtime_config(before, target)
        changed = [
            index
            for index, rows in enumerate(zip(before.splitlines(), after.splitlines()))
            if rows[0] != rows[1]
        ]
        self.assertEqual(changed, [11])
        self.assertIn('Extractor.modelPath: "/tmp/a02 strict70/HFNet-RT/"', after)
        self.assertIn("Extractor.nFeatures: 675", after)

    def test_wrong_token_cannot_create_claim_or_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=Path(directory) / "attempt_001")
            with mock.patch.object(runner.engine, "check") as checked, mock.patch.object(
                runner.engine, "launch_once"
            ) as launched:
                result = runner.run_strict70(spec, authorization_token="wrong")
            self.assertEqual(result["status"], "RUN_NOT_AUTHORIZED")
            checked.assert_not_called()
            launched.assert_not_called()
            self.assertFalse(spec.start_claim.exists())

    def test_v1_attempt_is_abandoned_unstarted_and_v2_is_fresh(self) -> None:
        receipt = json.loads(runner.V1_ABANDONMENT_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["status"], "V1_PREPARED_ONLY_ABANDONED_BEFORE_LOCK_OR_START"
        )
        self.assertFalse(receipt["execution_claims"]["hfnet_elf_started"])
        self.assertFalse(receipt["terminal_absence_observations"]["process_start_claim"]["exists"])
        self.assertFalse(receipt["terminal_absence_observations"]["run_result"]["exists"])
        self.assertNotEqual(runner.ATTEMPT, runner.base.ATTEMPT)
        self.assertIn("strict70", runner.ATTEMPT.as_posix())

    def test_v1_terminal_absence_is_rechecked_live_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "execution_lock": root / "lock.json",
                "process_start_claim": root / "claim.json",
                "run_result": root / "run_result.json",
                "result_directory": root / "result",
            }
            with mock.patch.object(runner, "V1_FORBIDDEN_TERMINAL_PATHS", paths):
                value = runner.audit_v1_abandoned_live_absence()
                self.assertTrue(value["all_forbidden_terminal_paths_absent"])
                paths["process_start_claim"].write_text("appeared", encoding="utf-8")
                with self.assertRaisesRegex(
                    runner.ContractError,
                    "ABANDONED_V1_TERMINAL_PATH_APPEARED:process_start_claim",
                ):
                    runner.audit_v1_abandoned_live_absence()

    def test_gpu_gate_requires_three_gib_and_zero_compute_apps(self) -> None:
        good_memory = SimpleNamespace(returncode=0, stdout="4096, 700, 3396\n", stderr="")
        no_apps = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[good_memory, no_apps]):
            value = runner._query_gpu_resource_gate()
        self.assertTrue(value["ready"])
        one_app = SimpleNamespace(returncode=0, stdout="42, hfnet, 128\n", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[good_memory, one_app]):
            value = runner._query_gpu_resource_gate()
        self.assertFalse(value["ready"])
        self.assertIn("GPU_COMPUTE_APPLICATION_PRESENT", value["errors"])


if __name__ == "__main__":
    unittest.main()
