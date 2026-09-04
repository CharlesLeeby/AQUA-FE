from __future__ import annotations

import unittest

from scripts.register_p07_preoutcome_allocations_v1 import (
    build_applicability_rows,
    build_registry_rows,
    validate_registered,
)


class P07PreoutcomeRegistrationV1Tests(unittest.TestCase):
    def test_intended_rows_match_frozen_capacity(self) -> None:
        registry = build_registry_rows()
        applicability = build_applicability_rows()
        self.assertEqual(len(registry), 60)
        self.assertEqual(len({row["registry_event_id"] for row in registry}), 60)
        self.assertTrue(all(row["status"] == "PLANNED" for row in registry))
        self.assertEqual(len(applicability), 20)
        self.assertTrue(all(row["resolution"] == "PENDING_APPLICABILITY" for row in applicability))

    def test_canonical_registration_is_complete_when_present(self) -> None:
        observed = validate_registered()
        self.assertIn(observed["registry_allocations_present"], {0, 60})
        self.assertIn(observed["pending_D_rows_present"], {0, 20})


if __name__ == "__main__":
    unittest.main()
