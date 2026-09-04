#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_p07_evaluator_precision_correction_lock_v1 as builder


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_fixture(root: Path) -> None:
    protocol = b"fixture isj-evaluator-v1 protocol\n"
    evaluator = (
        b"def parse_nanosecond_timestamp(raw):\n"
        b"    stripped = raw.strip()\n"
        b"    value = np.longdouble(stripped) / np.longdouble(\"1000000000\")\n"
        b"    parser.add_argument('--window', type=np.longdouble)\n"
        b"    return value\n"
    )
    core = (
        b"stamp_arr = np.asarray(stamps, dtype=np.longdouble)\n"
        b"exact = np.longdouble(\"1e-12\")\n"
        b"target_stamp = stamp_arr[left] + np.longdouble(str(delta_s))\n"
    )
    contents = {
        builder.PROTOCOL_RELATIVE: protocol,
        builder.EVALUATOR_RELATIVE: evaluator,
        builder.CORE_RELATIVE: core,
        builder.BUILDER_RELATIVE: b"fixture builder\n",
        builder.GOVERNANCE_TEST_RELATIVE: b"fixture governance test\n",
        builder.EVALUATOR_TEST_RELATIVE: b"fixture evaluator test\n",
        builder.CORE_TEST_RELATIVE: b"fixture core test\n",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    method_lock = {
        "schema_version": builder.EXPECTED_METHOD_SCHEMA,
        "status": builder.EXPECTED_METHOD_STATUS,
        "scientific_method_identity": "UNCHANGED_FROM_NATIVEQ_V3",
        "artifacts": [
            {
                "path": builder.PROTOCOL_RELATIVE.as_posix(),
                "sha256": digest(protocol),
                "size_bytes": len(protocol),
            },
            {
                "path": builder.EVALUATOR_RELATIVE.as_posix(),
                "sha256": "1" * 64,
                "size_bytes": 123,
            },
        ],
        "evaluation": {
            "evaluator": {
                "path": builder.PROTOCOL_RELATIVE.as_posix(),
                "sha256": digest(protocol),
                "size_bytes": len(protocol),
            }
        },
    }
    method_path = root / builder.METHOD_LOCK_RELATIVE
    method_path.parent.mkdir(parents=True, exist_ok=True)
    method_path.write_text(json.dumps(method_lock), encoding="utf-8")


class P07EvaluatorPrecisionCorrectionLockV1Tests(unittest.TestCase):
    def test_fixture_lock_is_additive_outcome_blind_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root)
            payload = builder.build_lock(
                root=root,
                frozen_at="2026-08-08T00:00:00+08:00",
            )

        self.assertEqual(payload["schema_version"], builder.SCHEMA_VERSION)
        self.assertEqual(payload["status"], builder.STATUS)
        self.assertEqual(
            payload["prior_implementation_binding"]["evaluator"]["sha256"],
            "1" * 64,
        )
        self.assertNotEqual(
            payload["corrected_implementation_binding"]["files"][0]["sha256"],
            "1" * 64,
        )
        self.assertTrue(payload["protocol_binding"]["unchanged"])
        self.assertEqual(
            payload["protocol_binding"]["parent_sha256"],
            payload["protocol_binding"]["current_sha256"],
        )
        audit = payload["outcome_blind_audit"]
        for key in (
            "real_trajectory_artifact_read",
            "ape_artifact_read",
            "rpe_artifact_read",
            "result_artifact_read",
            "vins_executed",
            "evaluator_executed",
            "evaluation_plan_generated",
            "backend_queue_generated",
            "workspace_discovery_used",
        ):
            self.assertFalse(audit[key])
        self.assertEqual(
            audit["builder_allowed_read_paths"],
            [path.as_posix() for path in builder.ALLOWED_READ_PATHS],
        )
        self.assertEqual(
            payload["correction_lock_hash"], builder.correction_lock_hash(payload)
        )

    def test_rejects_protocol_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root)
            (root / builder.PROTOCOL_RELATIVE).write_text(
                "changed protocol\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "protocol changed"):
                builder.build_lock(root=root)

    def test_rejects_missing_precision_patch_or_legacy_float64_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root)
            (root / builder.EVALUATOR_RELATIVE).write_text(
                "stamp_s = float(row[0]) * 1e-9\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "marker missing"):
                builder.build_lock(root=root)

    def test_rejects_when_current_evaluator_equals_parent_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root)
            method_path = root / builder.METHOD_LOCK_RELATIVE
            method = json.loads(method_path.read_text(encoding="utf-8"))
            current = builder.sha256_file(root / builder.EVALUATOR_RELATIVE)
            for record in method["artifacts"]:
                if record["path"] == builder.EVALUATOR_RELATIVE.as_posix():
                    record["sha256"] = current
            method_path.write_text(json.dumps(method), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pre-correction hash"):
                builder.build_lock(root=root)

    def test_checked_in_lock_rebuilds_exactly_from_source_allowlist(self) -> None:
        lock_path = builder.ROOT / builder.OUTPUT_RELATIVE
        checked_in = json.loads(lock_path.read_text(encoding="utf-8"))
        rebuilt = builder.build_lock(
            root=builder.ROOT,
            frozen_at=checked_in["frozen_at"],
            require_output_absent=False,
        )
        self.assertEqual(rebuilt, checked_in)
        self.assertEqual(
            checked_in["prior_implementation_binding"]["evaluator"]["sha256"],
            "21685f522c484d6cf333595a27b9566c1acd921e2fc0e060381e5749a6c0a8e1",
        )


if __name__ == "__main__":
    unittest.main()
