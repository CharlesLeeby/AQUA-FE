from __future__ import annotations

import csv
import io
import json
import unittest
from collections import Counter, defaultdict

from scripts.build_p06_final_freeze_v1 import (
    ARM_ORDER,
    DATASET_CHECKSUM_MANIFEST,
    D_ARM,
    FREEZE_HASHES,
    METHOD_LOCK,
    PROTOCOL,
    REQUIRED_ARMS,
    build_outputs,
    final_method_hash,
)


class P06FinalFreezeV1Tests(unittest.TestCase):
    def test_dataset_checksum_manifest_covers_41_unique_artifacts(self) -> None:
        outputs = build_outputs()
        lines = outputs[DATASET_CHECKSUM_MANIFEST].decode("ascii").splitlines()
        self.assertEqual(len(lines), 41)
        self.assertEqual(len({line.split("  ", 1)[1] for line in lines}), 41)

    def test_arm_order_is_balanced_and_has_only_conditional_d(self) -> None:
        outputs = build_outputs()
        rows = list(
            csv.DictReader(io.StringIO(outputs[ARM_ORDER].decode("utf-8")))
        )
        self.assertEqual(len(rows), 100)
        by_window = defaultdict(list)
        for row in rows:
            by_window[row["window_id"]].append(row)
        self.assertEqual(len(by_window), 20)
        first = Counter()
        for values in by_window.values():
            required = [row for row in values if row["applicability"] == "REQUIRED"]
            pending = [
                row
                for row in values
                if row["applicability"] == "PENDING_APPLICABILITY"
            ]
            self.assertEqual({row["arm"] for row in required}, set(REQUIRED_ARMS))
            self.assertEqual([row["arm"] for row in pending], [D_ARM])
            first[next(row["arm"] for row in required if row["order_position"] == "1")] += 1
        self.assertEqual(first, {arm: 5 for arm in REQUIRED_ARMS})
        self.assertNotIn("C_legacy_independent_classical_v3", {row["arm"] for row in rows})
        self.assertNotIn("B2_all_eligible", {row["arm"] for row in rows})

    def test_final_method_lock_is_self_consistent_and_narrowed(self) -> None:
        outputs = build_outputs()
        method = json.loads(outputs[METHOD_LOCK])
        self.assertEqual(final_method_hash(method), method["method_lock_hash"])
        self.assertEqual(method["status"], "FROZEN_FOR_P07_CONFIRMATORY_EXECUTION")
        self.assertEqual(
            method["H2_CONTROL_CONTRACT"], "NOT_APPLICABLE_CARRIER_FEEDBACK"
        )
        self.assertEqual(method["arms"]["conditional_before_trajectory_outcome"], [D_ARM])

    def test_protocol_and_freeze_manifest_bind_final_outputs(self) -> None:
        outputs = build_outputs()
        protocol = outputs[PROTOCOL].decode("ascii")
        method = json.loads(outputs[METHOD_LOCK])
        self.assertIn(method["method_lock_hash"], protocol)
        self.assertIn("RELATIVE_Q80_FALLBACK", protocol)
        freeze = outputs[FREEZE_HASHES].decode("ascii")
        self.assertIn("papers/ieee_sensors_journal_experiments/method_lock.json", freeze)
        self.assertIn("papers/ieee_sensors_journal_experiments/arm_order.csv", freeze)


if __name__ == "__main__":
    unittest.main()
