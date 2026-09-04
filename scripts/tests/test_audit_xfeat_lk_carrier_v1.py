from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from scripts import audit_superpoint_lk_carrier_v1 as audit_base
from scripts import audit_xfeat_lk_carrier_v1 as xfeat_audit
from scripts.tests import test_audit_superpoint_lk_carrier_v1 as fixtures


class XFeatFrozenAuditTests(unittest.TestCase):
    def test_source20_schema_and_method_are_fixed_in_result(self) -> None:
        frames20 = [fixtures._frame(index, source_code=20) for index in range(12)]
        result = xfeat_audit.evaluate(
            frames20,
            frames20,
            fixtures._camera(),
            fixtures._nonfeature_ok(),
            solver=fixtures._all_inliers,
        )
        self.assertTrue(result["pass"])
        self.assertEqual(
            result["schema_version"], xfeat_audit.XFEAT_AUDIT_SCHEMA_VERSION
        )
        self.assertEqual(
            result["method"], xfeat_audit.XFEAT_AUDIT_METHOD_SPEC.identity()
        )
        self.assertEqual(result["method"]["expected_observations_per_frame"], 350)
        self.assertEqual(
            result["observations_per_frame"],
            {
                "expected": 350,
                "observed": {"min": 350, "median": 350.0, "max": 350},
            },
        )
        self.assertEqual(
            result["contract"]["observations_per_frame"],
            result["observations_per_frame"],
        )
        self.assertEqual(result["contract"]["fixed_fields"]["source_code"], 20.0)

        frames10 = fixtures._frames()
        wrong_source = xfeat_audit.evaluate(
            frames10,
            frames10,
            fixtures._camera(),
            fixtures._nonfeature_ok(),
            solver=fixtures._all_inliers,
        )
        self.assertFalse(wrong_source["pass"])
        self.assertEqual(wrong_source["failed_gates"], ["contract"])
        self.assertIn(
            "CHANNEL_NOT_EXACT:source_code=20",
            wrong_source["contract"]["violation_counts"],
        )

        for count in (349, 351):
            with self.subTest(xfeat_observations=count):
                ids = np.arange(count, dtype=np.int64)
                candidate = [
                    fixtures._frame(index, ids, source_code=20)
                    for index in range(12)
                ]
                structural = xfeat_audit.evaluate_contract(
                    frames20,
                    candidate,
                    fixtures._camera(),
                    fixtures._nonfeature_ok(),
                    allow_prefix=False,
                )
                self.assertFalse(structural["pass"])
                self.assertEqual(
                    structural["violation_counts"][
                        "OBSERVATION_COUNT_NOT_EXACT"
                    ],
                    12,
                )

    def test_cli_and_python_wrapper_do_not_expose_schema_or_source_override(self) -> None:
        required = [
            "--reference-bag",
            "reference.bag",
            "--candidate-bag",
            "candidate.bag",
            "--camera-yaml",
            "camera.yaml",
        ]
        parsed = xfeat_audit.build_parser().parse_args(required)
        self.assertFalse(hasattr(parsed, "expected_source_code"))
        for override in (
            ["--expected-source-code", "10"],
            ["--schema-version", audit_base.SCHEMA_VERSION],
            ["--method-id", audit_base.SUPERPOINT_AUDIT_METHOD_ID],
        ):
            with self.subTest(override=override), self.assertRaises(SystemExit):
                xfeat_audit.build_parser().parse_args(required + override)

        frames20 = [fixtures._frame(index, source_code=20) for index in range(12)]
        with self.assertRaisesRegex(TypeError, "method_spec"):
            xfeat_audit.evaluate(
                frames20,
                frames20,
                fixtures._camera(),
                fixtures._nonfeature_ok(),
                method_spec=audit_base.SUPERPOINT_AUDIT_METHOD_SPEC,
            )
        with self.assertRaisesRegex(TypeError, "expected_source_code"):
            xfeat_audit.evaluate_contract(
                frames20,
                frames20,
                fixtures._camera(),
                fixtures._nonfeature_ok(),
                allow_prefix=False,
                expected_source_code=10,
            )

    def test_nonworkspace_help_and_output_identity_hash_fuse(self) -> None:
        script = Path(xfeat_audit.__file__).resolve()
        workspace = script.parents[1]
        environment = os.environ.copy()
        pythonpath = []
        for entry in environment.get("PYTHONPATH", "").split(os.pathsep):
            if not entry:
                continue
            try:
                if Path(entry).resolve() == workspace:
                    continue
            except OSError:
                pass
            pythonpath.append(entry)
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        with tempfile.TemporaryDirectory() as foreign_cwd:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=foreign_cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("XFeat-proposal", completed.stdout)
        self.assertNotIn("expected-source-code", completed.stdout)

        frames20 = [fixtures._frame(index, source_code=20) for index in range(12)]
        argv = [
            "--reference-bag",
            "reference.bag",
            "--candidate-bag",
            "candidate.bag",
            "--camera-yaml",
            "camera.yaml",
        ]
        pass_result = {
            "schema_version": "wrong-if-not-overwritten",
            "status": "PASS",
            "pass": True,
            "failed_gates": [],
        }
        with mock.patch.object(
            audit_base, "require_usac_magsac"
        ), mock.patch.object(
            audit_base, "load_camera_model", return_value=fixtures._camera()
        ), mock.patch.object(
            audit_base, "load_feature_frames", side_effect=[frames20, frames20]
        ), mock.patch.object(
            audit_base, "compare_nonfeature", return_value=fixtures._nonfeature_ok()
        ), mock.patch.object(
            audit_base, "evaluate", return_value=dict(pass_result)
        ) as evaluator, mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as stdout:
            rc = xfeat_audit.main(argv)
        self.assertEqual(rc, 0)
        payload = json.loads(stdout.getvalue())
        identity = xfeat_audit.XFEAT_AUDIT_METHOD_SPEC.identity()
        self.assertEqual(payload["schema_version"], identity["schema_version"])
        self.assertEqual(payload["method"], identity)
        self.assertEqual(payload["input"]["method"], identity)
        self.assertEqual(payload["audit_artifact"]["method"], identity)
        artifact = payload["audit_artifact"]
        self.assertEqual(Path(artifact["entrypoint"]["path"]), script)
        self.assertEqual(
            artifact["entrypoint"]["sha256"], audit_base._sha256_file(script)
        )
        base_path = Path(audit_base.__file__).resolve()
        self.assertEqual(Path(artifact["audit_base"]["path"]), base_path)
        self.assertEqual(
            artifact["audit_base"]["sha256"], audit_base._sha256_file(base_path)
        )
        self.assertIs(
            evaluator.call_args.kwargs["method_spec"],
            xfeat_audit.XFEAT_AUDIT_METHOD_SPEC,
        )


if __name__ == "__main__":
    unittest.main()
