#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "diagnostics"
    / "summarize_anyfeature_orb_init_audit_v1.py"
)
SPEC = importlib.util.spec_from_file_location("orb_init_summary", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SummaryHelpersTest(unittest.TestCase):
    def test_integer_stats(self):
        self.assertEqual(
            MODULE.integer_stats([1, 2, 9]),
            {"min": 1, "median": 2, "mean": 4.0, "max": 9},
        )

    def test_float_stats(self):
        result = MODULE.float_stats([0.1, 0.2, 0.3, 0.4])
        self.assertEqual(result["min"], 0.1)
        self.assertEqual(result["median"], 0.25)
        self.assertEqual(result["mean"], 0.25)
        self.assertEqual(result["max"], 0.4)

    def test_identity_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "artifact.bin"
            path.write_bytes(b"abc")
            result = MODULE.identity(path)
        self.assertEqual(result["size_bytes"], 3)
        self.assertEqual(
            result["sha256"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


if __name__ == "__main__":
    unittest.main()
