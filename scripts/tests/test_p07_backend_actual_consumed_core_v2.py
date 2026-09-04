from __future__ import annotations

import copy
import hashlib
import unittest

from scripts import p07_backend_actual_consumed_core_v2 as actual
from scripts import p07_backend_b0_plan_v2 as b0
from scripts.tests import test_p07_backend_b0_plan_v2 as b0_fixture


class P07BackendActualConsumedCoreV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = b0_fixture.P07BackendB0PlanV2Tests(
            methodName="test_exact_20_60_240_and_family_coverage"
        )
        self.fixture.setUp()
        self.b0_core = self.fixture._build()
        self.queue_authority = self.fixture.queue_authority
        self.payload = actual.build_actual_consumed_core(
            validated_b0_core=self.b0_core,
            frozen_queue_authority=self.queue_authority,
        )

    def validate(self, payload=None, queue_authority=None) -> str:
        return actual.validate_actual_consumed_core(
            self.payload if payload is None else payload,
            validated_b0_core=self.b0_core,
            frozen_queue_authority=(
                self.queue_authority if queue_authority is None else queue_authority
            ),
        )

    def test_exact_counts_self_hash_and_nonformal_policy(self) -> None:
        self.assertEqual(self.validate(), self.payload[actual.SELF_HASH_FIELD])
        expected = {
            "window_count": 20,
            "arm_count": 4,
            "cell_count": 80,
            "queue_binding_count": 240,
            "content_object_count": 179,
            "path_location_count": 202,
            "feature_bag_path_count": 60,
            "feature_content_object_count": 40,
            "feature_attestation_path_count": 60,
            "frontend_input_audit_path_count": 60,
            "unresolved_content_location_count": 3,
        }
        for key, value in expected.items():
            self.assertEqual(self.payload[key], value, key)
        self.assertEqual(
            self.payload["status"],
            "NONFORMAL_VALIDATED_MAPPING_NOT_EXECUTION_AUTHORITY",
        )
        self.assertEqual(
            self.payload["policy"],
            {
                "formal_artifact": False,
                "materialization_authorized": False,
                "execution_authorized": False,
                "trajectory_outcome_read": False,
                "raw_archives_are_runtime_inputs": False,
                "reference_or_eligibility_files_are_runtime_inputs": False,
                "unresolved_content_identity_blocks_execution": True,
            },
        )

    def test_cells_have_exact_roles_and_three_replays_reuse_one_cell(self) -> None:
        cells = {(row["window_id"], row["arm"]): row for row in self.payload["cells"]}
        bindings = self.payload["queue_bindings"]
        self.assertEqual(len(cells), 80)
        for key, cell in cells.items():
            self.assertEqual(cell["replay_indices"], [1, 2, 3])
            cell_bindings = [row for row in bindings if row["cell_id"] == cell["cell_id"]]
            self.assertEqual([row["replay_index"] for row in cell_bindings], [1, 2, 3])
            roles = {row["role"] for row in cell["location_bindings"]}
            if key[1] == b0.B0_ARM:
                self.assertTrue({"REPLAY_BAG", "PREPARATION_BAG"}.issubset(roles))
                by_role = {row["role"]: row["location_id"] for row in cell["location_bindings"]}
                self.assertEqual(by_role["REPLAY_BAG"], by_role["PREPARATION_BAG"])
            else:
                self.assertTrue(
                    {
                        "FEATURE_BAG",
                        "FEATURE_ATTESTATION",
                        "FRONTEND_INPUT_AUDIT",
                        "PREPARATION_BAG",
                    }.issubset(roles)
                )

    def test_feature_paths_are_preserved_while_content_is_deduplicated(self) -> None:
        locations = {
            row["location_id"]: row for row in self.payload["path_locations"]
        }
        feature_locations = [
            row for row in locations.values()
            if row["identity_status"] == "FROZEN_QUEUE_FEATURE_CONTENT_SHA256"
        ]
        self.assertEqual(len(feature_locations), 60)
        self.assertEqual(len({row["path"] for row in feature_locations}), 60)
        self.assertEqual(len({row["content_object_id"] for row in feature_locations}), 40)

        cells = {(row["window_id"], row["arm"]): row for row in self.payload["cells"]}
        window_id = sorted({key[0] for key in cells})[0]
        b1 = cells[(window_id, b0.B1_ARM)]
        proposed = cells[(window_id, b0.P_ARM)]
        def feature(cell):
            location_id = next(
                row["location_id"]
                for row in cell["location_bindings"]
                if row["role"] == "FEATURE_BAG"
            )
            return locations[location_id]
        b1_feature = feature(b1)
        p_feature = feature(proposed)
        self.assertNotEqual(b1_feature["path"], p_feature["path"])
        self.assertEqual(b1_feature["sha256"], p_feature["sha256"])
        self.assertEqual(
            b1_feature["content_object_id"], p_feature["content_object_id"]
        )

    def test_afrl_all_four_arms_bind_exact_bus_calibration(self) -> None:
        locations = {
            row["location_id"]: row for row in self.payload["path_locations"]
        }
        afrl_cells = [
            row for row in self.payload["cells"] if row["dataset_family"] == "afrl"
        ]
        self.assertEqual(len(afrl_cells), 4)
        for cell in afrl_cells:
            by_role = {row["role"]: row["location_id"] for row in cell["location_bindings"]}
            camera = locations[by_role["AFRL_BUS_CAMCHAIN"]]
            imu = locations[by_role["AFRL_IMU_CALIBRATION"]]
            self.assertEqual(camera["path"], b0.AFRL_BUS_CAMCHAIN_PATH)
            self.assertEqual(camera["sha256"], b0.AFRL_BUS_CAMCHAIN_SHA256)
            self.assertEqual(imu["path"], b0.AFRL_IMU_PATH)
            self.assertEqual(imu["sha256"], b0.AFRL_IMU_SHA256)

    def test_runtime_locations_exclude_raw_reference_and_eligibility_paths(self) -> None:
        forbidden = (
            "data_eligibility_manifest",
            "reference_audit",
            "groundtruth_files",
            "_raw_data.tar",
            "raw_input",
        )
        for location in self.payload["path_locations"]:
            self.assertFalse(any(value in location["path"] for value in forbidden))
        roles = {
            binding["role"]
            for cell in self.payload["cells"]
            for binding in cell["location_bindings"]
        }
        self.assertEqual(
            roles,
            {
                "REPLAY_BAG",
                "PREPARATION_BAG",
                "FEATURE_BAG",
                "FEATURE_ATTESTATION",
                "FRONTEND_INPUT_AUDIT",
                "AFRL_BUS_CAMCHAIN",
                "AFRL_IMU_CALIBRATION",
            },
        )

    def test_unknown_nested_hash_and_path_drift_are_rejected(self) -> None:
        variants = []
        extra = copy.deepcopy(self.payload)
        extra["unknown"] = True
        variants.append(extra)

        nested = copy.deepcopy(self.payload)
        nested["cells"][0]["location_bindings"][0]["unknown"] = True
        nested[actual.SELF_HASH_FIELD] = actual.document_hash(
            nested, actual.SELF_HASH_FIELD
        )
        variants.append(nested)

        path = copy.deepcopy(self.payload)
        path["path_locations"][0]["path"] = "logs/unknown/features.bag"
        path[actual.SELF_HASH_FIELD] = actual.document_hash(path, actual.SELF_HASH_FIELD)
        variants.append(path)

        digest_drift = copy.deepcopy(self.payload)
        digest_drift["content_objects"][0]["sha256"] = "0" * 64
        digest_drift[actual.SELF_HASH_FIELD] = actual.document_hash(
            digest_drift, actual.SELF_HASH_FIELD
        )
        variants.append(digest_drift)

        for value in variants:
            with self.subTest(hash=value.get(actual.SELF_HASH_FIELD)):
                with self.assertRaises(actual.ActualConsumedCoreV2Error):
                    self.validate(value)

    def test_replay_frontend_identity_drift_in_queue_authority_is_rejected(self) -> None:
        authority = copy.deepcopy(dict(self.queue_authority))
        row = next(item for item in authority["rows"] if item["arm"] != b0.B0_ARM)
        row["feature_bag"] = row["feature_bag"] + ".different"
        authority["full_row_hashes"] = [
            b0._full_queue_row_hash(item) for item in authority["rows"]
        ]
        authority["ordered_full_row_hashes_sha256"] = hashlib.sha256(
            b0.canonical_json(authority["full_row_hashes"]).encode("utf-8")
        ).hexdigest()
        authority[b0.QUEUE_AUTHORITY_ENVELOPE_HASH] = b0.document_hash(
            authority, b0.QUEUE_AUTHORITY_ENVELOPE_HASH
        )
        altered_authority = b0.ValidatedQueueAuthority(
            authority, token=b0._QUEUE_AUTHORITY_SENTINEL
        )
        with self.assertRaises(actual.ActualConsumedCoreV2Error):
            actual.build_actual_consumed_core(
                validated_b0_core=self.b0_core,
                frozen_queue_authority=altered_authority,
            )


if __name__ == "__main__":
    unittest.main()
