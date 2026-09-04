from __future__ import annotations

import json
import unittest

from scripts.audit_p07_b1_frontend_export_v2 import (
    parse_guard_path_without_resolving_workspace_symlink,
)
from scripts.build_p07_b1_auditor_correction_lock_v2 import OUTPUT, build_lock, lock_hash


class P07B1AuditorCorrectionV2Tests(unittest.TestCase):
    def test_guard_path_stays_under_workspace_visible_logs_path(self) -> None:
        lock = build_lock()
        command_log = next(
            item["path"] for item in lock["artifacts"] if item["path"].endswith("command.log")
        )
        from pathlib import Path

        path = parse_guard_path_without_resolving_workspace_symlink(Path(command_log))
        self.assertTrue(str(path).startswith("/home/ma/AQUA-FE_WS/logs/"))

    def test_lock_hash_is_canonical(self) -> None:
        payload = build_lock()
        self.assertEqual(payload["correction_lock_hash"], lock_hash(payload))
        if OUTPUT.exists():
            observed = json.loads(OUTPUT.read_text(encoding="utf-8"))
            self.assertEqual(observed["correction_lock_hash"], lock_hash(observed))


if __name__ == "__main__":
    unittest.main()
