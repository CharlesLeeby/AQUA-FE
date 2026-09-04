#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.validate_p06_screening_closeout_v2 import (
    resolve_registered_code_issues,
    strict_hash_manifest,
    validate_reference_exclusion,
)


class P06ScreeningCloseoutV2Test(unittest.TestCase):
    def test_strict_manifest_accepts_one_registered_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hashes.sha256"
            digest = hashlib.sha256(b"content").hexdigest()
            path.write_text(f"{digest}  scripts/example.py\n", encoding="utf-8")
            entries, issues = strict_hash_manifest(path)
            self.assertEqual(entries, {"scripts/example.py": digest})
            self.assertEqual(issues, [])

    def test_strict_manifest_rejects_duplicate_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hashes.sha256"
            digest = "0" * 64
            path.write_text(
                f"{digest}  scripts/example.py\n"
                f"{digest}  scripts/example.py\n"
                f"{digest}  ../escape.py\n",
                encoding="utf-8",
            )
            _, issues = strict_hash_manifest(path)
            self.assertTrue(any("duplicate" in issue for issue in issues))
            self.assertTrue(any("path_invalid" in issue for issue in issues))

    def test_strict_manifest_rejects_malformed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hashes.sha256"
            path.write_text("not-a-hash  scripts/example.py\n", encoding="utf-8")
            entries, issues = strict_hash_manifest(path)
            self.assertEqual(entries, {})
            self.assertTrue(any("malformed" in issue for issue in issues))

    def test_v3_manifest_resolves_base_code_registration_issue(self) -> None:
        issues = [
            "code_not_registered:scripts/run_p06_ros_screening_v3.py",
            "missing_run_artifact",
        ]
        resolved = resolve_registered_code_issues(
            issues,
            {"scripts/run_p06_ros_screening_v3.py": "0" * 64},
        )
        self.assertEqual(resolved, ["missing_run_artifact"])

    def test_registered_cave_reference_exclusion_is_self_consistent(self) -> None:
        self.assertEqual(
            validate_reference_exclusion("afrl", "cave_gennie"), []
        )


if __name__ == "__main__":
    unittest.main()
