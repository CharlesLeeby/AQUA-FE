#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import build_hfnet_v6_samehistory_positive_roster_lock_v2 as builder
from scripts import run_hfnet_v6_samehistory_positive_roster_v1 as runner_v1
from scripts import run_hfnet_v6_samehistory_positive_roster_v2 as subject


POSE = "0.1 -0.2 0.3 0 0 0 1"


class DecimalTimestampRealityRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def trajectory(self, tokens) -> Path:
        path = self.root / "trajectory.txt"
        path.write_text(
            "".join(f"{token} {POSE}\n" for token in tokens),
            encoding="ascii",
        )
        return path

    def test_official_fixed_decimal_integral_ns_is_accepted(self) -> None:
        stamps = [1_000_000, 2_000_000, 3_000_000]
        path = self.trajectory(
            ["1000000.000000", "2000000.000000", "3000000.000000"]
        )
        observed = subject.parse_trajectory(path, stamps)
        self.assertTrue(observed["valid"])
        self.assertEqual(observed["pose_count"], 3)
        self.assertEqual(observed["coverage_fraction"], 1.0)
        self.assertEqual(observed["longest_contiguous_count"], 3)
        self.assertEqual(observed["timestamp_serialization"], "INTEGRAL_DECIMAL_NS")

    def test_v1_reality_bug_is_reproduced_without_touching_frozen_runner(self) -> None:
        path = self.trajectory(["1000000.000000"])
        observed = runner_v1.parse_trajectory(path, [1_000_000])
        self.assertFalse(observed["valid"])
        self.assertEqual(observed["pose_count"], 0)
        self.assertEqual(observed["errors"], ["ROW_1_PARSE"])

    def test_exact_256ns_bridge_is_fixed_and_257ns_is_rejected(self) -> None:
        accepted = subject.parse_trajectory(
            self.trajectory(["1000256.000000"]), [1_000_000]
        )
        self.assertTrue(accepted["valid"])
        rejected = subject.parse_trajectory(
            self.trajectory(["1000257.000000"]), [1_000_000]
        )
        self.assertFalse(rejected["valid"])
        self.assertIn("ROW_1_ASSOCIATION_NOT_UNIQUE", rejected["errors"])

    def test_fractional_nanosecond_and_ambiguous_header_are_rejected(self) -> None:
        fractional = subject.parse_trajectory(
            self.trajectory(["1000000.500000"]), [1_000_000]
        )
        self.assertFalse(fractional["valid"])
        self.assertEqual(fractional["errors"], ["ROW_1_PARSE"])
        ambiguous = subject.parse_trajectory(
            self.trajectory(["1200.000000"]), [1_000, 1_400]
        )
        self.assertFalse(ambiguous["valid"])
        self.assertEqual(
            ambiguous["errors"], ["ROW_1_ASSOCIATION_NOT_UNIQUE"]
        )

    def test_mapping_is_strict_and_cannot_reuse_a_camera_header(self) -> None:
        observed = subject.parse_trajectory(
            self.trajectory(["1000000.000000", "1000100.000000"]),
            [1_000_000, 2_000_000],
        )
        self.assertFalse(observed["valid"])
        self.assertIn("ROW_2_SOURCE_HEADER_REUSED", observed["errors"])

    def test_earliest_longest_contiguous_run_uses_realistic_header_spacing(self) -> None:
        stamps = [1_000_000 + index * 50_000_000 for index in range(12)]
        selected = stamps[1:5] + stamps[7:11]
        observed = subject.parse_trajectory(
            self.trajectory([f"{stamp}.000000" for stamp in selected]), stamps
        )
        self.assertTrue(observed["valid"])
        self.assertEqual(
            observed["longest_contiguous_relative_indices_inclusive"], [1, 4]
        )


class SupersedingAuthorityTest(unittest.TestCase):
    def test_runner_rebinds_every_mutable_attempt_namespace(self) -> None:
        self.assertTrue(str(subject.PUBLICATION_POINTER).endswith("_v2.json"))
        self.assertTrue(str(subject.ROSTER_ROOT).endswith("_roster_v2"))
        self.assertEqual(subject._v1.RUNNER, subject.RUNNER)
        self.assertEqual(subject._v1.PUBLICATION_POINTER, subject.PUBLICATION_POINTER)
        self.assertEqual(subject._v1.ROSTER_ROOT, subject.ROSTER_ROOT)
        self.assertEqual(subject._v1.CASE_SCHEMA, subject.CASE_SCHEMA)
        self.assertEqual(subject._v1.ROSTER_LOCK_SCHEMA, subject.ROSTER_LOCK_SCHEMA)
        self.assertEqual(subject._v1.PREPARED_SCHEMA, subject.PREPARED_SCHEMA)
        self.assertIs(subject._v1.parse_trajectory, subject.parse_trajectory)

    def test_v2_builder_uses_new_pointer_root_schema_and_tokens(self) -> None:
        self.assertEqual(builder._v1.PUBLICATION_POINTER, builder.PUBLICATION_POINTER)
        self.assertEqual(builder._v1.ROSTER_RUNTIME_ROOT, builder.ROSTER_RUNTIME_ROOT)
        self.assertEqual(builder._v1.CASE_SCHEMA, builder.CASE_SCHEMA)
        self.assertEqual(builder._v1.ROSTER_SCHEMA, builder.ROSTER_SCHEMA)
        self.assertNotEqual(
            builder.authorization_token("a05_3300_3700"),
            builder._v1.sha256_bytes(
                (
                    "AQUA-FE HFNet v6 same-history one-shot authorization v1\0"
                    "a05_3300_3700"
                ).encode("utf-8")
            ),
        )

    def test_one_real_core_spec_is_read_only_and_points_only_to_v2(self) -> None:
        row = builder._v1.CASES[0]
        spec = builder._v1.build_core_spec(row)
        self.assertEqual(spec["schema_version"], builder.CASE_SCHEMA)
        self.assertEqual(
            Path(spec["attempt_root"]),
            builder.ROSTER_RUNTIME_ROOT / "a05_3300_3700/attempt_001",
        )
        self.assertFalse(Path(spec["attempt_root"]).exists())


if __name__ == "__main__":
    unittest.main()
