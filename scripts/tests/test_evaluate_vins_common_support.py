#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.evaluate_vins_common_support import (
    clean_json_value,
    load_tum_reference,
    load_vins_body_csv,
    legacy_nearest_reuse_stats,
    parse_nanosecond_timestamp,
    parse_named_paths,
    parse_named_floats,
    parse_evo_rmse,
    format_identity_tum_line,
)


class EvaluateVinsCommonSupportTest(unittest.TestCase):
    def test_load_vins_reads_wxyz_output_as_xyzw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vio.csv"
            path.write_text(
                "1000000000,1,2,3,0.5,0.1,0.2,0.3,0,0,0,\n",
                encoding="utf-8",
            )
            series = load_vins_body_csv(path)
        np.testing.assert_allclose(series.stamps, [1.0])
        np.testing.assert_allclose(series.positions, [[1, 2, 3]])
        assert series.quaternions_xyzw is not None
        np.testing.assert_allclose(series.quaternions_xyzw, [[0.1, 0.2, 0.3, 0.5]])

    def test_epoch_nanoseconds_do_not_round_through_float64(self) -> None:
        first_ns = "1542888916043622300"
        second_ns = "1542888916043622400"  # 100 ns later.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vio.csv"
            path.write_text(
                f"{first_ns},0,0,0,1,0,0,0\n"
                f"{second_ns},1,0,0,1,0,0,0\n",
                encoding="utf-8",
            )
            series = load_vins_body_csv(path)

        self.assertEqual(series.stamps.dtype, np.dtype(np.longdouble))
        self.assertGreater(series.stamps[1], series.stamps[0])
        self.assertAlmostEqual(
            float((series.stamps[1] - series.stamps[0]) * 1e9),
            100.0,
            delta=0.1,
        )
        self.assertEqual(series.stamps[0], parse_nanosecond_timestamp(first_ns))

    def test_nanosecond_parser_rejects_seconds_or_scientific_notation(self) -> None:
        with self.assertRaisesRegex(ValueError, "integer nanoseconds"):
            parse_nanosecond_timestamp("1542888916.0")
        with self.assertRaisesRegex(ValueError, "integer nanoseconds"):
            parse_nanosecond_timestamp("1e9")

    def test_load_tum_preserves_orientation_and_rejects_mixed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.tum"
            path.write_text("0 1 2 3 0 0 0 1\n1 2 3 4 0 0 0 1\n", encoding="utf-8")
            series = load_tum_reference(path)
            assert series.quaternions_xyzw is not None
            np.testing.assert_allclose(series.quaternions_xyzw[:, 3], [1, 1])
            path.write_text("0 1 2 3\n1 2 3 4 0 0 0 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mixed position-only"):
                load_tum_reference(path)

    def test_named_path_parser_requires_unique_name_value_pairs(self) -> None:
        self.assertEqual(parse_named_paths(["P=/tmp/p"], "--arm"), {"P": Path("/tmp/p")})
        with self.assertRaisesRegex(ValueError, "NAME=PATH"):
            parse_named_paths(["broken"], "--arm")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_named_paths(["P=/tmp/a", "P=/tmp/b"], "--arm")
        self.assertEqual(
            parse_named_floats(["P=-0.05"], "--arm-time-offset-s"),
            {"P": -0.05},
        )

    def test_json_cleaner_converts_nonfinite_values_to_null(self) -> None:
        self.assertEqual(
            clean_json_value({"finite": 1.0, "nan": float("nan")}),
            {"finite": 1.0, "nan": None},
        )

    def test_legacy_reuse_diagnostic_counts_repeated_reference_use(self) -> None:
        stats = legacy_nearest_reuse_stats(
            [0.0, 0.1, 0.2, 0.9, 1.0], [0.0, 1.0]
        )
        self.assertEqual(stats["legacy_pair_count"], 5)
        self.assertEqual(stats["legacy_unique_reference_used"], 2)
        self.assertEqual(stats["legacy_max_reference_reuse"], 3)
        self.assertEqual(stats["legacy_unique_assignment_pair_count"], 2)

    def test_tum_serialization_uses_17_significant_digits(self) -> None:
        line = format_identity_tum_line(
            1542888916.0436223, np.array([0.12345678901234567, 2.0, 3.0])
        )
        self.assertIn("1542888916.0436223", line)
        self.assertIn("0.12345678901234566", line)
        self.assertTrue(line.endswith(" 0 0 0 1\n"))

    def test_evo_rmse_parser(self) -> None:
        self.assertEqual(parse_evo_rmse("rmse 0.125\n"), 0.125)


if __name__ == "__main__":
    unittest.main()
