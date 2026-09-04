#!/usr/bin/env python3
"""Static contract tests for the one-shot A08 frontend runner."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "run_a08_recovered_july_natural_history_frontends_v1.py"
SPEC = importlib.util.spec_from_file_location("a08_frontend_runner_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class FrontendRunnerContractTest(unittest.TestCase):
    def test_execution_tree_is_exactly_the_frozen_overlay(self) -> None:
        self.assertEqual(
            RUNNER.verify_execution_tree(),
            {
                "file_count": 192,
                "tree_sha256":
                    "654f3d921fdb5971ce1e4da04b367e6c987011eb5bb5d72ebb1805cb38b7f1c9",
                "transitive_closure_exact": True,
                "ambient_extra_source_files": 0,
            },
        )

    def test_klt_command_is_full_history_export_only(self) -> None:
        command, env = RUNNER.command_for("klt")
        self.assertEqual(command[-6:], ["aqualoc_archaeo", "8", "0", "4660", "klt", "2"])
        self.assertEqual(env["RAW_BAG"], str(RUNNER.RAW_BAG))
        self.assertEqual(env["RUN_VINS"], "0")
        self.assertEqual(env["FORCE_RAW"], "0")
        self.assertEqual(env["FORCE_EXPORT"], "1")
        self.assertNotIn("EXPORT_START_OFFSET", env)
        self.assertNotIn("EXPORT_DURATION", env)
        self.assertEqual(env["RESET_RECOVERED_EXPORT_IDS"], "0")
        self.assertEqual(env["EXPORT_MAX_FEATURES"], "350")
        self.assertEqual(env["MEASUREMENT_SELECTION"], "0")
        self.assertEqual(env["VINS_SAFE_SOURCE_SELECTION"], "0")

    def test_xfeat_command_keeps_the_frozen_july_a08_profile(self) -> None:
        command, env = RUNNER.command_for("xfeat")
        self.assertEqual(
            command[-6:],
            ["aqualoc_archaeo", "8", "0", "4660", "hybrid_xfeat", "2"],
        )
        self.assertEqual(env["AQUAFE_SEEDCHAIN_PROFILE"], "lineage_early_seed_scan")
        self.assertEqual(env["LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME"], "2")
        self.assertEqual(env["RUN_VINS"], "0")

    def test_all_frozen_arbitration_profiles_are_accepted(self) -> None:
        source = inspect.getsource(RUNNER.find_xfeat_runs)
        for profile in (
            "mirror_densecap",
            "klt_safe_fallback",
            "oldcontract_microburst",
            "late_dense_normal",
            "degraded_mature_dense",
            "degraded_early_dense",
            "degraded_early_long",
            "degraded_early_sparse_mature",
            "low_grid_rejected_rich",
            "mature_lineage",
        ):
            self.assertIn(f'"{profile}"', source)

    def test_expected_feature_schedule_is_odd_source_frames(self) -> None:
        self.assertEqual(RUNNER.CAMERA_COUNT, 4661)
        self.assertEqual(RUNNER.FEATURE_COUNT, 2330)
        self.assertEqual(1 + 2 * (RUNNER.FEATURE_COUNT - 1), 4659)

    def test_output_names_do_not_overlap_historical_evidence(self) -> None:
        self.assertIn("recoveredjuly_hist0000_4660", RUNNER.KLT_TAG)
        self.assertIn("recoveredjuly_hist0000_4660", RUNNER.XFEAT_TAG_BASE)
        self.assertNotIn("jul14frozen3way", RUNNER.KLT_TAG)
        self.assertNotIn("jul14frozen3way", RUNNER.XFEAT_TAG_BASE)

    def test_cuda_environment_imports_only_the_overlay_exporter(self) -> None:
        env = RUNNER.environment_updates()
        self.assertEqual(env["ROOT"], str(RUNNER.OVERLAY))
        self.assertTrue(env["PYTHONPATH"].startswith(f"{RUNNER.OVERLAY}:"))
        self.assertTrue(env["PATH"].startswith(f"{RUNNER.CUDA_BIN}:"))
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_process_environment_is_a_sealed_whitelist(self) -> None:
        env = RUNNER.environment_updates()
        for forbidden in (
            "BASH_ENV",
            "ENV",
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "PYTHONSTARTUP",
            "PYTHONINSPECT",
        ):
            self.assertNotIn(forbidden, env)
        self.assertEqual(env["HOME"], "/home/ma")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["LANG"], "C.UTF-8")

    def test_child_does_not_merge_the_ambient_environment(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("{**os.environ, **env}", source)
        self.assertNotIn("{**os.environ, **environment_updates()}", source)
        self.assertIn("env=env,", source)


if __name__ == "__main__":
    unittest.main()
