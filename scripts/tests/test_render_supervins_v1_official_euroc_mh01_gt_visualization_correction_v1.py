import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts import render_supervins_v1_official_euroc_mh01_gt_visualization_correction_v1 as renderer


class InputAndBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.associated = renderer.read_associated_rows()
        cls.rpe = renderer.read_rpe_rows()

    def test_all_sealed_input_pins_match(self):
        audit = renderer.inspect_expected_inputs()
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["failures"], [])
        self.assertEqual(len(audit["checks"]), 6)

    def test_sealed_csv_support_counts_only(self):
        self.assertEqual(len(self.associated), 1799)
        self.assertEqual(len(self.rpe), 1789)
        self.assertEqual(self.associated[0]["estimate_row_index"], 0)
        self.assertEqual(self.associated[-1]["estimate_row_index"], 1798)
        self.assertTrue(all(row["se3_ape_m"] >= 0.0 for row in self.associated))
        self.assertTrue(all(row["se3_rpe_m"] >= 0.0 for row in self.rpe))

    def test_renderer_has_no_scientific_numeric_dependency(self):
        source = renderer.SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse({"numpy", "scipy", "matplotlib", "pandas"} & imported)
        self.assertNotIn("metrics.json", source)
        self.assertNotIn("align_se3", source)

    def test_fresh_additive_root_is_absent_before_run(self):
        self.assertFalse(renderer.EVIDENCE_ROOT.exists())


class FigureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.associated = renderer.read_associated_rows()
        cls.rpe = renderer.read_rpe_rows()

    def test_trajectory_panels_share_equal_metres_per_pixel(self):
        svg, audit = renderer.trajectory_svg(self.associated)
        self.assertTrue(audit["equal_metric_aspect_all_axes"])
        values = [
            audit["shared_metres_per_pixel"],
            audit["xy_x_metres_per_pixel"],
            audit["xy_y_metres_per_pixel"],
            audit["xz_x_metres_per_pixel"],
            audit["xz_z_metres_per_pixel"],
        ]
        self.assertLessEqual(max(values) - min(values), 1e-15)
        self.assertIn('id="metric-aspect-audit"', svg)
        self.assertIn("Sim(3) diagnostic", svg)
        self.assertIn('stroke-dasharray="7 4"', svg)

    def test_error_axes_start_at_exact_zero(self):
        svg, audit = renderer.error_svg(self.associated, self.rpe)
        self.assertTrue(audit["all_axis_lower_bounds_exact_zero"])
        for domain in (audit["ape_domain"], audit["rpe_domain"]):
            self.assertEqual(domain["xmin"], 0.0)
            self.assertEqual(domain["ymin"], 0.0)
            self.assertGreater(domain["xmax"], 0.0)
            self.assertGreater(domain["ymax"], 0.0)
        self.assertIn('id="nonnegative-axis-audit"', svg)
        self.assertIn("begin at exactly zero", svg)

    def test_error_figure_rejects_negative_sealed_display_value(self):
        associated = [dict(row) for row in self.associated[:20]]
        rpe = [dict(row) for row in self.rpe[:10]]
        associated[3]["se3_ape_m"] = -1e-6
        with self.assertRaises(ValueError):
            renderer.error_svg(associated, rpe)

    def test_exact_additive_file_set_is_frozen(self):
        expected = renderer.exact_output_paths()
        self.assertEqual(len(expected), 7)
        self.assertEqual(expected, sorted(expected))
        self.assertIn("artifact-manifest.json", expected)
        self.assertIn("visualization-correction-receipt.json", expected)
        self.assertNotIn(str(renderer.SEALED_ATTEMPT), "\n".join(expected))


class IntegrityPrimitiveTests(unittest.TestCase):
    def test_canonical_self_hash_round_trip_and_tamper_detection(self):
        base = {"schema_version": "synthetic", "nested": {"b": 2, "a": 1}}
        sealed = renderer.add_canonical_self_hash(base, "self_hash")
        self.assertTrue(renderer.verify_canonical_self_hash(sealed, "self_hash"))
        tampered = json.loads(json.dumps(sealed))
        tampered["nested"]["a"] = 9
        self.assertFalse(renderer.verify_canonical_self_hash(tampered, "self_hash"))

    def test_tree_digest_is_sorted_and_exact(self):
        entries = {
            "b": {"sha256": "2" * 64, "size_bytes": 2},
            "a": {"sha256": "1" * 64, "size_bytes": 1},
        }
        rows = [
            {"path": "a", "sha256": "1" * 64, "size_bytes": 1},
            {"path": "b", "sha256": "2" * 64, "size_bytes": 2},
        ]
        expected = hashlib.sha256(renderer.compact_json_bytes(rows)).hexdigest()
        self.assertEqual(renderer.canonical_tree_digest(entries), expected)

    def test_exclusive_writer_is_immutable_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.svg"
            identity = renderer.write_bytes_exclusive(path, b"<svg/>\n")
            self.assertEqual(identity["mode"], "0444")
            self.assertEqual(identity["nlink"], 1)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
            with self.assertRaises(FileExistsError):
                renderer.write_bytes_exclusive(path, b"changed")
            self.assertEqual(path.read_bytes(), b"<svg/>\n")


if __name__ == "__main__":
    unittest.main()
