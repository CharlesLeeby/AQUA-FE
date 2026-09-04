from __future__ import annotations

import unittest

from scripts import build_p07_frontend_orchestration_correction_lock_v6 as builder
from scripts import run_p07_frontend_queue_v6 as queue


class P07FrontendOrchestrationV6Tests(unittest.TestCase):
    def test_lock_changes_only_audit_resolution_compatibility(self) -> None:
        payload = builder.build_lock()
        self.assertEqual(payload["allowed_queue_indices"], list(range(31, 61)))
        self.assertFalse(payload["correction"]["frontend_scientific_command_changed"])
        self.assertFalse(payload["correction"]["lineage_or_exact_drop_contract_changed"])
        self.assertEqual(payload["orchestration_lock_hash"], builder.lock_hash(payload))

    def test_bus_outside_terminal_evidence_is_complete(self) -> None:
        from scripts import run_p07_frontend_queue_v4 as v4_queue

        self.assertTrue(v4_queue.window_is_terminal_complete("afrl:bus_outside:0001"))


if __name__ == "__main__":
    unittest.main()
