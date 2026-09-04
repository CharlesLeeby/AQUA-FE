#!/usr/bin/env python3

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from scripts.audit_p06_screening_equivalence import audit_rows
from scripts import p02_window_selection, p06_window_selection_v2
from scripts.build_p06_window_selection_v2 import absolute_stratum
from uw_frontend.evaluation.run_frontend_eval import _diagnostics_for_output_tracks
from uw_frontend.geometry.grid import grid_stats
from uw_frontend.ros.export_vins_features import _backend_reliability, _window_screening_metrics
from uw_frontend.tracking.track_state import TrackSet, TrackerDiagnostics


def _tracks(ids: list[int], points: list[tuple[float, float]]) -> TrackSet:
    count = len(ids)
    array = np.asarray(points, dtype=np.float32).reshape(count, 2)
    return TrackSet(
        ids=np.asarray(ids, dtype=np.int64),
        prev_points=array.copy(),
        points=array.copy(),
        ages=np.ones((count,), dtype=np.int32),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
        local_texture=np.ones((count,), dtype=np.float32),
        qualities=np.ones((count,), dtype=np.float32),
        sources=["klt"] * count,
    )


class P06WindowScreeningContractTest(unittest.TestCase):
    def test_ros_metrics_match_direct_runner_semantics(self) -> None:
        tracks = _tracks([2, 3], [(10.0, 10.0), (110.0, 90.0)])
        previous = {1, 2, 9}
        quality = SimpleNamespace(flat_region_ratio=0.35, degradation_score=0.42)

        metrics, current = _window_screening_metrics(
            tracks,
            (100, 120),
            quality,
            previous,
            rows=2,
            cols=3,
        )
        fallback = TrackerDiagnostics(0, 0, 0, 0, 0.0, 1.0, 1.0)
        direct_diagnostics = _diagnostics_for_output_tracks(tracks, previous, fallback)
        direct_grid = grid_stats(tracks.points, (100, 120), rows=2, cols=3)

        self.assertEqual(current, {2, 3})
        self.assertEqual(metrics["grid_coverage"], direct_grid.coverage)
        self.assertEqual(
            metrics["dropout_ratio"],
            direct_diagnostics.dropped_features / direct_diagnostics.tracked_before_filter,
        )
        self.assertEqual(metrics["flat_region_ratio"], 0.35)
        self.assertEqual(metrics["degradation_score"], 0.42)

    def test_first_published_frame_has_zero_dropout(self) -> None:
        tracks = _tracks([0], [(20.0, 20.0)])
        quality = SimpleNamespace(flat_region_ratio=0.0, degradation_score=0.0)
        metrics, _ = _window_screening_metrics(
            tracks,
            (100, 100),
            quality,
            set(),
        )
        self.assertEqual(metrics["dropout_ratio"], 0.0)

    def test_default_backend_quality_accepts_source_constants(self) -> None:
        tracks = _tracks([0], [(20.0, 20.0)])
        tracks.sources = ["xfeat_confirmed"]
        quality = _backend_reliability(
            tracks,
            mode="default",
            xfeat_quality_const=0.73,
        )
        self.assertAlmostEqual(float(quality[0]), 0.73, places=6)

    def test_equivalence_audit_accepts_constant_index_offset(self) -> None:
        direct = [
            {
                "frame_index": str(2210 + index),
                "grid_coverage": "0.5",
                "dropout_ratio": "0.1",
                "flat_region_ratio": "0.2",
                "degradation_score": "0.3",
            }
            for index in range(2)
        ]
        ros = [
            {
                **row,
                "frame_index": str(index),
            }
            for index, row in enumerate(direct)
        ]
        result, _ = audit_rows(direct, ros, tolerance=1e-12)
        self.assertEqual(result["status"], "PASS")

    def test_equivalence_audit_rejects_metric_drift(self) -> None:
        direct = [
            {
                "frame_index": "10",
                "grid_coverage": "0.5",
                "dropout_ratio": "0.1",
                "flat_region_ratio": "0.2",
                "degradation_score": "0.3",
            }
        ]
        ros = [{**direct[0], "frame_index": "0", "dropout_ratio": "0.11"}]
        result, _ = audit_rows(direct, ros, tolerance=1e-12)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["metric_mismatch_count"]["dropout_ratio"], 1)

    def test_v2_entrypoint_does_not_relabel_v1(self) -> None:
        self.assertEqual(p02_window_selection.PROTOCOL_VERSION, "isj-window-selection-v1")
        self.assertEqual(p06_window_selection_v2.PROTOCOL_VERSION, "isj-window-selection-v2")

    def test_v2_absolute_thresholds_retain_guard_band(self) -> None:
        self.assertEqual(absolute_stratum(0.17), "low")
        self.assertEqual(absolute_stratum(0.10), "normal")
        self.assertEqual(absolute_stratum(0.15), "unclassified")


if __name__ == "__main__":
    unittest.main()
