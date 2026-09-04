#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.validate_p06_final_artifacts_v2 import validate_selected_consistency


def selected_fixture() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    selected: list[dict[str, str]] = []
    audit: list[dict[str, str]] = []
    for stratum in ("low", "normal"):
        for index in range(10):
            sequence = f"S{index % 7}"
            row = {
                "window_id": f"{stratum}:{index}",
                "dataset_family": f"family{index % 3}",
                "data_domain": f"domain{index % 3}",
                "sequence": sequence,
                "window_index": str(index),
                "window_start_s": str(45.0 * index),
                "window_end_s": str(45.0 * (index + 1)),
                "texture_stratum": stratum,
                "score": "0.2",
                "input_frame_count": "900",
            }
            selected.append(dict(row))
            audit.append(
                {
                    **row,
                    "selected_final": "true",
                    "history_excluded": "false",
                    "reference_support_pass": "true",
                }
            )
    return selected, audit


class P06FinalArtifactsV2Test(unittest.TestCase):
    def test_consistent_10_plus_10_selection_passes(self) -> None:
        selected, audit = selected_fixture()
        self.assertEqual(validate_selected_consistency(selected, audit), [])

    def test_selected_reference_failure_is_rejected(self) -> None:
        selected, audit = selected_fixture()
        audit[0]["reference_support_pass"] = "false"
        issues = validate_selected_consistency(selected, audit)
        self.assertIn("selected_reference_support_fail:low:0", issues)

    def test_selected_audit_field_mismatch_is_rejected(self) -> None:
        selected, audit = selected_fixture()
        audit[0]["score"] = "0.3"
        issues = validate_selected_consistency(selected, audit)
        self.assertIn("selected_audit_field_mismatch:low:0:score", issues)


if __name__ == "__main__":
    unittest.main()
