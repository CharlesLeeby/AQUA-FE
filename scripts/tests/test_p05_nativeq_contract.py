#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.audit_p05_modern_xfeat import (
    audit_determinism,
    parse_assignment,
    strictly_increasing,
)
from scripts.build_nativeq_legacy_method_lock import config_chain, payload_hash


class P05NativeQualityContractTest(unittest.TestCase):
    def test_probe_assignment_resolves_a_path(self) -> None:
        label, path = parse_assignment("ntnu=logs/example", "probe")
        self.assertEqual(label, "ntnu")
        self.assertTrue(Path(path).is_absolute())

    def test_feature_timestamps_must_be_strictly_increasing(self) -> None:
        self.assertTrue(strictly_increasing([1.0, 1.1, 1.2]))
        self.assertFalse(strictly_increasing([1.0, 1.0, 1.2]))
        self.assertFalse(strictly_increasing([]))

    def test_determinism_requires_bag_and_metrics_byte_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            for name, content in (("features.bag", b"bag"), ("frontend_metrics.csv", b"csv")):
                (left / name).write_bytes(content)
                (right / name).write_bytes(content)
            result = audit_determinism("left", left, "right", right)
            self.assertTrue(result["pass"])
            (right / "frontend_metrics.csv").write_bytes(b"changed")
            result = audit_determinism("left", left, "right", right)
            self.assertFalse(result["pass"])

    def test_method_hash_excludes_generation_time_and_hash_field(self) -> None:
        base = {"status": "candidate", "generated_at_utc": "a"}
        with_hash = {**base, "candidate_lock_hash": "ignored"}
        changed_time = {**base, "generated_at_utc": "b"}
        self.assertEqual(payload_hash(base), payload_hash(with_hash))
        self.assertEqual(payload_hash(base), payload_hash(changed_time))

    def test_p05_config_chain_reaches_klt_base(self) -> None:
        root = Path(__file__).resolve().parents[2]
        chain = config_chain(
            root / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"
        )
        self.assertEqual(chain[-1].name, "isj_p05_xfeat_pairwise_nativeq.yaml")
        self.assertIn("klt_frontend.yaml", [path.name for path in chain])


if __name__ == "__main__":
    unittest.main()
