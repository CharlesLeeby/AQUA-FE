from __future__ import annotations

import copy
import unittest
from unittest import mock

from scripts import build_p07_backend_formalization_adoption_v1 as adoption
from scripts import build_p07_backend_formalization_review_evidence_v1 as evidence


class P07BackendFormalizationReviewLeafV1Tests(unittest.TestCase):
    """Nonrecursive validator leaves executed by the retained review runner."""

    def test_administrative_receipt_rejects_true_or_short_method_inventory(self) -> None:
        identity = {
            "reviewer_id": "global",
            "reviewer_instance": "global-01",
            "reviewer_role": adoption.GLOBAL_REVIEWER_ROLE,
        }
        receipt = adoption.build_administrative_test_receipt(
            receipt_role="GLOBAL_STABILITY_ADMINISTRATIVE",
            completed_at="2026-08-08T13:00:00+08:00",
            producer_identity=identity,
            command_argv=adoption.ADMINISTRATIVE_TEST_ARGV,
            test_methods=adoption.ADMINISTRATIVE_TEST_METHODS,
            tests_run=len(adoption.ADMINISTRATIVE_TEST_METHODS),
            return_code=0,
            stdout_sha256="a" * 64,
            stderr_sha256="b" * 64,
            candidate_source_bindings_hash="c" * 64,
        )
        for mutation in ("true", "short"):
            changed = copy.deepcopy(receipt)
            if mutation == "true":
                changed["command_argv"] = ["true"]
            else:
                changed["test_methods"] = changed["test_methods"][:-1]
                changed["tests_run"] -= 1
            changed[adoption.ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD] = (
                adoption.administrative_test_receipt_hash(changed)
            )
            with self.subTest(mutation=mutation):
                with self.assertRaises(adoption.AdoptionError):
                    adoption._validate_administrative_test_receipt(
                        changed,
                        expected_role="GLOBAL_STABILITY_ADMINISTRATIVE",
                        expected_source_bindings_hash="c" * 64,
                    )

    def test_full_stack_receipt_rejects_true_fake_count_or_old_time(self) -> None:
        expected = [
            "scripts.tests.test_p07_backend_formalization_review_leaf_v1."
            "P07BackendFormalizationReviewLeafV1Tests.test_full_stack_receipt_rejects_true_fake_count_or_old_time"
        ]
        identity = {
            "reviewer_id": "independent",
            "reviewer_instance": "independent-01",
            "reviewer_role": adoption.INDEPENDENT_REVIEWER_ROLE,
        }
        receipt = evidence._build_test_receipt_from_execution(
            receipt_role=evidence.RECEIPT_ROLES[1],
            reviewer_identity=identity,
            completed_at="2026-08-08T14:00:00+08:00",
            command_argv=evidence.FULL_STACK_ARGV,
            test_methods=expected,
            return_code=0,
            stdout_sha256="d" * 64,
            stderr_sha256="e" * 64,
            source_artifacts_hash="f" * 64,
            expected_test_methods=expected,
        )
        for mutation in ("true", "count"):
            changed = copy.deepcopy(receipt)
            if mutation == "true":
                changed["command_argv"] = ["true"]
            else:
                changed["tests_run"] = 99
            changed["test_receipt_hash"] = evidence.test_receipt_hash(changed)
            with self.subTest(mutation=mutation):
                with self.assertRaises(evidence.ReviewEvidenceError):
                    evidence.validate_test_receipt(
                        changed,
                        source_artifacts_hash="f" * 64,
                        expected_test_methods=expected,
                    )

    def test_nested_runner_depth_is_fail_closed_before_subprocess(self) -> None:
        with mock.patch.dict(
            "os.environ", {"AQUAFE_P07_REVIEW_RUNNER_DEPTH": "1"}
        ):
            with self.assertRaisesRegex(evidence.ReviewEvidenceError, "nested"):
                evidence.run_administrative_tests(
                    root=evidence.ROOT,
                    receipt_role="EXTERNAL_MANIFEST_PREFLIGHT",
                    producer_identity={
                        "reviewer_id": "builder",
                        "reviewer_instance": "builder-01",
                        "reviewer_role": "EXTERNAL_MANIFEST_BUILDER",
                    },
                    candidate_source_bindings_hash="0" * 64,
                    guard_paths=(),
                )


if __name__ == "__main__":
    unittest.main()
