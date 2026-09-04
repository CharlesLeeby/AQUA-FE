from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_hfnet_v6_samehistory_accuracy_prefreeze_seal_v1 as M


class AccuracyPrefreezeSealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # One live read-only integration build exercises every frozen identity,
        # prepared manifest, historical source, absence gate, and evo pin.  It
        # deliberately becomes inapplicable once the one-shot experiment starts.
        cls.document = M.dry_run_document()

    def test_live_document_is_outcome_blind_and_valid(self) -> None:
        M.validate_document(self.document)
        self.assertEqual(self.document["schema_version"], M.SCHEMA_VERSION)
        self.assertEqual(self.document["status"], M.STATUS)
        self.assertTrue(all(value is False for value in self.document["claims"].values()))
        self.assertFalse(self.document["outcome_firewall"]["ape_or_rpe_computed"])
        self.assertFalse(self.document["outcome_firewall"]["winner_or_ranking_computed"])

    def test_exact_case_order_and_admission_partition(self) -> None:
        self.assertEqual(self.document["case_order"], list(M.CASE_ORDER))
        self.assertEqual(len(self.document["cases"]), 10)
        rows = {row["case_id"]: row for row in self.document["cases"]}
        self.assertEqual(set(rows), set(M.CASE_ORDER))
        for case_id in M.CASE_ORDER:
            expected = (
                "CONDITIONAL_ON_FUTURE_HFNET_RUNABILITY_PASS_AND_FOURWAY_GATE"
                if case_id in M.CONDITIONAL_CASES
                else "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND"
            )
            self.assertEqual(rows[case_id]["accuracy_admission"], expected)
            self.assertEqual(
                rows[case_id]["structural_na_reasons"],
                list(M.STRUCTURAL_NA_REASONS.get(case_id, ())),
            )

    def test_only_superseding_v2_execution_authority_is_accepted(self) -> None:
        adjudication = self.document["execution_authority_adjudication"]
        self.assertEqual(
            adjudication["active_execution_generation"],
            "V2_PRESTART_PARSER_SUPERSESSION",
        )
        self.assertFalse(adjudication["v1_execution_authorities_accepted"])
        self.assertTrue(str(M.RUNTIME_ROOT).endswith("samehistory_old_positive_roster_v2"))
        self.assertEqual(
            M.EXPECTED_PREPARED_SCHEMA,
            "aqua-fe-hfnet-v6-samehistory-positive-prepared-v2",
        )
        self.assertEqual(
            self.document["authorities"]["whole_roster_pointer"]["sha256"],
            "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
        )
        self.assertEqual(
            self.document["authorities"]["prepared_runner"]["sha256"],
            "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
        )
        self.assertEqual(
            self.document["authorities"][
                "prestart_parser_supersession_protocol"
            ]["sha256"],
            "cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7",
        )

    def test_every_case_pins_spec_prepared_headers_sources_and_future_paths(self) -> None:
        expected_camera_counts = {
            "a05_3300_3700": 401,
            "a07_10800_11200": 401,
            "a08_4500_4660": 161,
            "a09_6000_6200": 201,
            "fjord1_s83_d10": 200,
            "mclab1_s60_d15": 300,
            "cirs_s575_d30": 150,
            "cirs_s900_d30": 150,
            "a02_7600_8000": 401,
            "mclab2_s110_d10": 200,
        }
        for row in self.document["cases"]:
            for identity_name in ("case_spec", "prepared_manifest"):
                identity = row[identity_name]
                self.assertEqual(set(identity), {"path", "size_bytes", "sha256"})
                self.assertTrue(Path(identity["path"]).is_absolute())
                self.assertEqual(len(identity["sha256"]), 64)
            expected_prepared = M.EXPECTED_PREPARED_MANIFESTS[row["case_id"]]
            self.assertEqual(
                (
                    row["prepared_manifest"]["size_bytes"],
                    row["prepared_manifest"]["sha256"],
                ),
                expected_prepared,
            )
            headers = row["score_camera_headers"]
            self.assertEqual(headers["count"], expected_camera_counts[row["case_id"]])
            self.assertEqual(len(headers["ordered_integer_ns_ascii_lf_sha256"]), 64)
            self.assertIn("reference", row["historical_sources"])
            self.assertIn("learned_plus_klt", row["historical_sources"])
            self.assertIn("klt", row["historical_sources"])
            future_paths = row["future_hfnet_outputs_observed_absent"]
            self.assertEqual(len(future_paths), 9)
            self.assertTrue(all(Path(path).is_absolute() for path in future_paths.values()))
            accuracy = row["future_accuracy_publication"]
            self.assertFalse(accuracy["retry_permitted"])
            self.assertFalse(accuracy["replacement_output_permitted"])
            self.assertEqual(
                accuracy["execution_lock"],
                str(M.FUTURE_EXECUTION_LOCK_ROOT / f"{row['case_id']}.json"),
            )
            self.assertEqual(
                accuracy["hfnet_timestamp_bridge_receipt"],
                str(
                    M.FUTURE_EXECUTION_LOCK_ROOT
                    / f"{row['case_id']}.hfnet_timestamp_bridge_receipt.json"
                ),
            )

    def test_a08_binds_all_repeats_without_selecting_r3(self) -> None:
        row = next(
            row for row in self.document["cases"] if row["case_id"] == "a08_4500_4660"
        )
        self.assertEqual(row["accuracy_admission"], "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND")
        for arm in ("learned_plus_klt", "klt"):
            source = row["historical_sources"][arm]
            self.assertEqual(len(source["trajectory_candidates"]), 5)
            self.assertEqual(
                [entry["repeat"] for entry in source["trajectory_candidates"]],
                [1, 2, 3, 4, 5],
            )
            self.assertEqual(
                source["single_trajectory_selection"],
                "NOT_APPLICABLE_STRUCTURAL_NA",
            )
            self.assertFalse(source["authorized_as_future_metric_input"])
            self.assertNotIn("trajectory", source)
        self.assertEqual(
            row["historical_sources"]["learned_plus_klt"]["repeat_manifest"]["sha256"],
            "f6a807900e08955748695edc9a5c88a8b640dee240bc72b49d2e7029b223d2eb",
        )

    def test_final_prefreeze_and_evo_runtime_are_exactly_pinned(self) -> None:
        self.assertEqual(
            self.document["authorities"]["analysis_grid_prefreeze"],
            {
                "path": str(M.PREFREEZE.resolve()),
                "size_bytes": 16833,
                "sha256": "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d",
            },
        )
        code = self.document["analysis_code_identities"]
        self.assertEqual(
            code["roster_evaluator_core"]["path"],
            str(M.ANALYSIS_EVALUATOR.resolve()),
        )
        self.assertEqual(
            code["formal_accuracy_controller"]["path"],
            str(M.FORMAL_ACCURACY_CONTROLLER.resolve()),
        )
        evo = self.document["evo_environment"]
        tree = evo["evo_implementation_tree"]
        self.assertEqual(tree["file_count"], 45)
        self.assertEqual(tree["total_bytes"], 473395)
        self.assertEqual(tree["tree_sha256"], M.EVO_TREE_SHA256)
        self.assertEqual(tree["digest_algorithm"], M.EVO_TREE_ALGORITHM)
        self.assertEqual(evo["numpy"]["version"], "1.24.4")
        self.assertEqual(evo["scipy"]["version"], "1.10.1")

    def test_evo_commands_and_crosscheck_evidence_are_exact(self) -> None:
        contract = self.document["evo_environment"]["verification_contract"]
        self.assertEqual(
            contract["ape"]["argv_template"],
            [
                str(M.EVO_APE),
                "tum",
                "{REFERENCE_ALL_COMMON_TUM}",
                "{ESTIMATE_ALL_COMMON_TUM}",
                "-a",
                "-r",
                "trans_part",
                "--t_max_diff",
                "1e-9",
                "--t_offset",
                "0",
            ],
        )
        rpe = contract["rpe"]
        self.assertNotIn("-a", rpe["argv_template"])
        self.assertNotIn("-s", rpe["argv_template"])
        self.assertIn("--pairs_from_reference", rpe["argv_template"])
        self.assertTrue(rpe["unweighted_mean_of_segment_rmse_forbidden"])
        self.assertTrue(contract["real_resampled_orientations_required"])
        self.assertTrue(contract["caller_supplied_scalar_rmse_forbidden"])
        self.assertEqual(
            contract["primary_metric_status_before_crosscheck"],
            "EVO_CROSSCHECK_PENDING",
        )

    def test_analysis_code_identity_placeholders_fail_closed(self) -> None:
        incomplete = dict(M.EXPECTED_ANALYSIS_CODE_IDENTITIES)
        incomplete["roster_evaluator_core"] = (M.ANALYSIS_EVALUATOR, None, None)
        with mock.patch.object(M, "EXPECTED_ANALYSIS_CODE_IDENTITIES", incomplete):
            with self.assertRaisesRegex(
                M.BuildError, "ANALYSIS_CODE_IDENTITY_NOT_FROZEN"
            ):
                M.analysis_code_identities()

    def test_frame_bridge_contract_forbids_cirs_camera_extrinsic_substitution(self) -> None:
        frames = self.document["analysis_contract"]["frame_contract"]
        self.assertEqual(
            frames["AQUALOC_ARCHAEOLOGY"]["estimate_static_transform"],
            "IMU_T_camera",
        )
        self.assertEqual(frames["NTNU"]["all_static_bridges"], "IDENTITY")
        self.assertEqual(
            frames["CIRS"]["estimate_static_transform"],
            "IMU_T_vehicle",
        )
        self.assertTrue(
            frames["CIRS"][
                "historical_online_camera_extrinsic_ignored_for_body_bridge"
            ]
        )
        self.assertTrue(frames["CIRS"]["two_sided_inverse_verified"])
        self.assertLessEqual(frames["CIRS"]["two_sided_inverse_max_abs_error"], 1e-15)
        self.assertTrue(
            frames["NTNU"]["old_world_T_cam0_or_body_T_cam0_contracts_superseded"]
        )

    def test_grid_contract_is_integer_exact_and_rejects_wrong_count(self) -> None:
        stamps = [1_000_000_003, 1_050_000_003, 1_200_000_003]
        grid = M.grid_contract(stamps, 3)
        self.assertEqual(grid["count"], 3)
        expected = b"1000000003\n1100000003\n1200000003\n"
        self.assertEqual(grid["ordered_integer_ns_lf_sha256"], M.sha256_bytes(expected))
        with self.assertRaises(M.BuildError):
            M.grid_contract(stamps, 4)

    def test_file_identity_and_absence_reject_symlinks_including_dangling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_bytes(b"stable")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(M.BuildError):
                M.file_identity(link)
            dangling = root / "dangling"
            dangling.symlink_to(root / "missing")
            with self.assertRaises(M.BuildError):
                M.require_absent(dangling, "dangling")

    def test_prepared_result_directory_must_be_plain_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result"
            result.mkdir()
            self.assertEqual(
                M.require_plain_directory(result, "result", empty=True),
                str(result),
            )
            (result / "unexpected.outcome").write_bytes(b"forbidden")
            with self.assertRaises(M.BuildError):
                M.require_plain_directory(result, "result", empty=True)
            link = root / "result-link"
            link.symlink_to(result, target_is_directory=True)
            with self.assertRaises(M.BuildError):
                M.require_plain_directory(link, "result-link")

    def test_publication_is_complete_and_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "seal.json"
            first_payload = b'{"complete":true}\n'
            identity = M.publish_file_noreplace(destination, first_payload)
            self.assertEqual(destination.read_bytes(), first_payload)
            self.assertEqual(identity["sha256"], M.sha256_bytes(first_payload))
            with self.assertRaises(M.BuildError):
                M.publish_file_noreplace(destination, b'{"complete":false}\n')
            self.assertEqual(destination.read_bytes(), first_payload)
            self.assertEqual(
                [path.name for path in destination.parent.iterdir()],
                ["seal.json"],
            )

    def test_formal_publish_requires_the_exact_explicit_token(self) -> None:
        with self.assertRaisesRegex(
            M.BuildError, "PUBLISH_AUTHORIZATION_TOKEN_MISMATCH"
        ):
            M.publish("WRONG_TOKEN")
        self.assertTrue(M._absent(M.PUBLICATION_PATH))

    def test_validator_rejects_any_true_claim(self) -> None:
        tampered = copy.deepcopy(self.document)
        tampered["claims"]["accuracy_measured"] = True
        with self.assertRaises(M.BuildError):
            M.validate_document(tampered)

    def test_validator_rejects_grid_or_future_path_tampering(self) -> None:
        grid_tampered = copy.deepcopy(self.document)
        grid_tampered["cases"][0]["analysis_grid"]["count"] += 1
        with self.assertRaises(M.BuildError):
            M.validate_document(grid_tampered)
        path_tampered = copy.deepcopy(self.document)
        path_tampered["cases"][0]["future_accuracy_publication"][
            "process_claim"
        ] = "/tmp/result_selected_claim"
        with self.assertRaises(M.BuildError):
            M.validate_document(path_tampered)

    def test_validator_rejects_evo_or_controller_contract_tampering(self) -> None:
        controller = self.document["future_accuracy_controller_contract"]
        self.assertEqual(
            controller["canonical_prestart_seal_path"], str(M.PUBLICATION_PATH)
        )
        self.assertFalse(controller["caller_selected_prestart_seal_path_permitted"])
        self.assertFalse(
            controller["seal_supplied_self_identity_is_sufficient_authorization"]
        )
        evo_tampered = copy.deepcopy(self.document)
        evo_tampered["evo_environment"]["verification_contract"]["rpe"][
            "argv_template"
        ].append("-a")
        with self.assertRaises(M.BuildError):
            M.validate_document(evo_tampered)
        controller_tampered = copy.deepcopy(self.document)
        controller_tampered["future_accuracy_controller_contract"][
            "retry_permitted"
        ] = True
        with self.assertRaises(M.BuildError):
            M.validate_document(controller_tampered)

    def test_canonical_json_is_deterministic_and_forbids_nan(self) -> None:
        left = M.canonical_json({"z": 1, "a": [2, 3]})
        right = M.canonical_json({"a": [2, 3], "z": 1})
        self.assertEqual(left, right)
        self.assertEqual(json.loads(left), {"a": [2, 3], "z": 1})
        with self.assertRaises(ValueError):
            M.canonical_json({"bad": float("nan")})

    def test_dry_run_did_not_publish_or_reserve_accuracy_namespace(self) -> None:
        self.assertTrue(M._absent(M.PUBLICATION_PATH))
        self.assertTrue(M._absent(M.FUTURE_ACCURACY_ROOT))
        self.assertTrue(M._absent(M.FUTURE_EXECUTION_LOCK_ROOT))


if __name__ == "__main__":
    unittest.main()
