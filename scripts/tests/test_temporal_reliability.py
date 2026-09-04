from __future__ import annotations

import unittest

from uw_frontend.geometry.master_candidate_stream import TrackEvidence
from uw_frontend.quality.temporal_reliability import (
    CalibrationRow,
    FEATURE_NAMES,
    TemporalSnapshot,
    audit_calibration_rows,
    build_calibration_rows,
    calibration_audit,
    fit_pooled_reliability,
    selector_features,
)


def _evidence(track_id: int, *, source="learned_xfeat", current_e=0.2, age=5):
    return TrackEvidence(
        track_id=track_id,
        source=source,
        u=100.0,
        v=80.0,
        q_lower=0.5,
        normalized_residual=current_e,
        age=age,
        ncc=0.8,
        fb_error=0.2,
        survival_count=age,
        residual_history=(0.1, 0.2, 0.3),
        motion_ratio=1.0,
    )


def _snapshots(sequence: str, source_group: str, lineage_id: int, fail_frame=None):
    source = {"klt": "klt_base", "learned": "learned_xfeat", "classical": "classical_gftt"}[source_group]
    return [
        TemporalSnapshot(
            sequence_id=sequence,
            lineage_id=lineage_id,
            source_group=source_group,
            geometry_stratum="planar" if sequence.endswith("cal") else "degraded",
            frame_index=frame,
            evidence=_evidence(lineage_id, source=source, age=frame + 3),
            klt_valid=frame != fail_frame,
            geometry_correct=frame != fail_frame,
        )
        for frame in range(6)
    ]


def _model_rows():
    rows = []
    for sequence, split, offset in (
        ("train_a", "train", 0),
        ("train_b", "train", 100),
        ("held_cal", "calibration", 200),
    ):
        for source_index, source in enumerate(("klt", "learned", "classical")):
            for index in range(6):
                label = (index + source_index + offset) % 2
                base = 0.15 + 0.12 * index
                features = (
                    base,
                    0.3 + 0.5 * label,
                    0.2 + 0.6 * label,
                    0.4 + 0.5 * label,
                    0.3 + 0.6 * label,
                    0.2 + 0.7 * label,
                )
                rows.append(
                    CalibrationRow(
                        sequence_id=sequence,
                        lineage_id=offset + source_index * 100 + index,
                        source_group=source,
                        geometry_stratum="planar" if source_index == 1 else "degraded",
                        decision_frame=index,
                        label_end_frame=index + 5,
                        split=split,
                        features=features,
                        label=label,
                    )
                )
    return rows


class TemporalReliabilityTests(unittest.TestCase):
    def test_features_ignore_source_and_current_residual(self) -> None:
        learned = _evidence(1, source="learned_xfeat", current_e=0.0)
        classical = _evidence(1, source="classical_gftt", current_e=4.0)
        self.assertEqual(selector_features(learned), selector_features(classical))
        self.assertEqual(len(selector_features(learned)), len(FEATURE_NAMES))

    def test_horizon_label_and_tail_censoring(self) -> None:
        snapshots = _snapshots("train", "learned", 10, fail_frame=2)
        rows = build_calibration_rows(
            snapshots,
            sequence_splits={"train": "train"},
            horizon_frames=2,
        )
        labels = {row.decision_frame: row.label for row in rows}
        self.assertEqual(labels[0], 0)
        self.assertEqual(labels[1], 0)
        self.assertEqual(labels[2], 1)
        self.assertEqual(max(labels), 3)
        self.assertNotIn(4, labels)

    def test_sequence_split_overlap_is_rejected(self) -> None:
        rows = _model_rows()
        row = rows[0]
        conflicting = CalibrationRow(
            **{**row.__dict__, "decision_frame": 999, "split": "calibration"}
        )
        with self.assertRaisesRegex(ValueError, "sequence"):
            audit_calibration_rows([*rows, conflicting])

    def test_pooled_model_is_deterministic_and_q_lower_has_no_floor(self) -> None:
        rows = _model_rows()
        first = fit_pooled_reliability(rows)
        second = fit_pooled_reliability(rows)
        self.assertEqual(first.model_hash, second.model_hash)
        features = [[0.0] * len(FEATURE_NAMES), [1.0] * len(FEATURE_NAMES)]
        p_hat = first.p_hat(features)
        q_lower = first.q_lower(features)
        self.assertTrue(((q_lower >= 0.0) & (q_lower <= p_hat)).all())
        self.assertTrue((q_lower == 0.0).any())
        audit = calibration_audit(first, rows)
        names = {row["group"] for row in audit}
        self.assertIn("overall", names)
        self.assertTrue({"source:klt", "source:learned", "source:classical"} <= names)

    def test_three_source_groups_are_required_for_freeze(self) -> None:
        rows = [row for row in _model_rows() if row.source_group != "classical"]
        with self.assertRaisesRegex(ValueError, "classical"):
            fit_pooled_reliability(rows)


if __name__ == "__main__":
    unittest.main()

