#!/usr/bin/env python3
"""Tests for the sealed-evidence-only A02 r3 report renderer."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


ROOT = Path("/home/ma/AQUA-FE_WS")
SOURCE = ROOT / "scripts/build_matched_birth_r4_vins_report_v2.py"
SPEC = importlib.util.spec_from_file_location("matched_birth_report_v2", SOURCE)
assert SPEC is not None and SPEC.loader is not None
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ReportV2Tests(unittest.TestCase):
    def test_live_prepublication_check(self) -> None:
        value = report.execute("check")
        self.assertEqual(value["status"], "PASS_REPORT_V2_PREPUBLICATION")
        self.assertFalse(value["write_performed"])
        self.assertEqual(len(value["documents"]), 4)

    def test_source_has_no_scientific_or_process_dependency(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(imported.isdisjoint({
            "numpy", "rosbag", "subprocess", "trajectory_eval_core",
            "evaluate_vins_common_support", "evo",
        }))
        for forbidden in ("ape.txt", "rosbag.Bag", "Popen(", "subprocess.run"):
            self.assertNotIn(forbidden, source)

    def test_post_gate_mutation_is_rejected_even_with_new_self_hash(self) -> None:
        value = json.loads(report.POST.read_bytes())
        value["strict_gates"]["rpe_valid"] = False
        value["post_hash"] = report._self_hash(value, "post_hash")
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="report-post-mutation-") as td:
            path = Path(td) / "post.json"
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            pins = dict(report.PINNED_GOVERNANCE_RECORDS)
            data = path.read_bytes()
            pins["post"] = (hashlib.sha256(data).hexdigest(), len(data))
            with mock.patch.object(report, "POST", path), \
                    mock.patch.object(report, "PINNED_GOVERNANCE_RECORDS", pins):
                with self.assertRaisesRegex(report.ReportError, "strict post"):
                    report.execute("check")

    def test_publication_status_and_closeout_record_mutations_are_rejected(self) -> None:
        cases = (
            ("INTENT", report.INTENT, "publication_intent_hash", "status",
             "MUTATED_STATUS"),
            ("CLOSEOUT", report.CLOSEOUT, "publication_closeout_hash", "output_manifest",
             {"path": "mutated", "sha256": "0" * 64, "size_bytes": 1}),
        )
        for attribute, original, hash_field, field, replacement in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                    dir=ROOT, prefix="report-publication-mutation-") as td:
                value = json.loads(original.read_bytes())
                value[field] = replacement
                value[hash_field] = report._self_hash(value, hash_field)
                path = Path(td) / "mutated.json"
                path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
                pins = dict(report.PINNED_GOVERNANCE_RECORDS)
                key = "intent" if attribute == "INTENT" else "closeout"
                data = path.read_bytes()
                pins[key] = (hashlib.sha256(data).hexdigest(), len(data))
                with mock.patch.object(report, attribute, path), \
                        mock.patch.object(report, "PINNED_GOVERNANCE_RECORDS", pins):
                    with self.assertRaises(report.ReportError):
                        report.execute("check")

    def test_corrected_seal_must_be_the_frozen_file_record(self) -> None:
        value = json.loads(report.CORRECTED_SEAL.read_bytes())
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="report-corrected-") as td:
            path = Path(td) / "corrected.json"
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            pins = dict(report.PINNED_GOVERNANCE_RECORDS)
            data = path.read_bytes()
            pins["corrected"] = (hashlib.sha256(data).hexdigest(), len(data))
            with mock.patch.object(report, "CORRECTED_SEAL", path), \
                    mock.patch.object(report, "PINNED_GOVERNANCE_RECORDS", pins):
                with self.assertRaisesRegex(report.ReportError, "frozen input record"):
                    report.execute("check")

    def test_analysis_receipt_binds_renderer_source(self) -> None:
        with report.ExitStack() as stack:
            evidence = report._load_evidence(stack)
            documents = report._render(evidence)
            receipt = report._receipt(evidence, documents)
        renderer = next(record for record in receipt["source_records"]
                        if record["path"] == str(report.SOURCE.relative_to(report.ROOT)))
        content = report.SOURCE.read_bytes()
        self.assertEqual(renderer["size_bytes"], len(content))
        self.assertEqual(renderer["sha256"], hashlib.sha256(content).hexdigest())

    def test_role_metric_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
                dir=report.RESULT.parent, prefix="report-role-drift-") as td:
            copied = Path(td) / "result"
            shutil.copytree(report.RESULT, copied)
            target = copied / "verification/common_support_metrics.csv"
            data = target.read_bytes().replace(b"0.7413695191864242", b"0.7413695191864243")
            target.write_bytes(data)
            with mock.patch.object(report, "RESULT", copied):
                with self.assertRaises(report.ReportError):
                    report.execute("check")

    def test_extra_symlink_and_hardlink_are_rejected(self) -> None:
        for kind in ("extra", "symlink", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                    dir=report.RESULT.parent, prefix=f"report-{kind}-") as td:
                copied = Path(td) / "result"
                shutil.copytree(report.RESULT, copied)
                if kind == "extra":
                    (copied / "extra.txt").write_text("x")
                elif kind == "symlink":
                    (copied / "extra-link").symlink_to("bound_summary_v1.json")
                else:
                    os.link(copied / "bound_summary_v1.json", copied / "extra-hard")
                with mock.patch.object(report, "RESULT", copied):
                    with self.assertRaises(report.ReportError):
                        report.execute("check")

    def test_atomic_publication_in_disposable_namespace(self) -> None:
        with tempfile.TemporaryDirectory(
                dir=report.RESULT.parent, prefix="report-publish-") as td:
            destination = Path(td) / "analysis"
            staging = Path(td) / ".analysis.staging"
            with mock.patch.object(report, "ANALYSIS", destination), \
                    mock.patch.object(report, "STAGING", staging):
                value = report.execute("write-once")
            self.assertEqual(value["status"], "PASS_REPORT_V2_PUBLISHED")
            self.assertFalse(staging.exists())
            self.assertEqual(
                {item.name for item in destination.iterdir()},
                {report.REPORT_NAME, report.ANALYSIS_NAME, report.STATS_NAME,
                 report.FIGURES_NAME, report.RECEIPT_NAME})
            for item in destination.iterdir():
                self.assertEqual(item.stat().st_mode & 0o777, 0o444)
                self.assertEqual(item.stat().st_nlink, 1)
            receipt = json.loads((destination / report.RECEIPT_NAME).read_bytes())
            self.assertEqual(receipt["analysis_hash"],
                             report._self_hash(receipt, "analysis_hash"))

    def test_existing_destination_or_staging_is_no_clobber(self) -> None:
        for existing in ("destination", "staging"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory(
                    dir=report.RESULT.parent, prefix="report-reserved-") as td:
                destination = Path(td) / "analysis"
                staging = Path(td) / ".analysis.staging"
                (destination if existing == "destination" else staging).mkdir()
                with mock.patch.object(report, "ANALYSIS", destination), \
                        mock.patch.object(report, "STAGING", staging):
                    with self.assertRaisesRegex(report.ReportError, "already exists"):
                        report.execute("write-once")

    def test_report_claim_language_is_bounded(self) -> None:
        with report.ExitStack() as stack:
            evidence = report._load_evidence(stack)
            documents = report._render(evidence)
        text = b"\n".join(documents.values()).decode("utf-8")
        for required in ("post-result exploratory", "n=1", "not independent samples",
                         "not independent external ground truth"):
            self.assertIn(required, text)
        self.assertNotIn("independent implementation", text)
        self.assertNotIn("statistically significant", text)


if __name__ == "__main__":
    unittest.main()
