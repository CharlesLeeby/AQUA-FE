from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import genpy
import rosbag
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, Imu, PointCloud

from scripts import audit_quality_partition as auditor
from scripts import rewrite_quality_partition as rewriter
from scripts import verify_a02_long_component_continuation_v2_3 as v2_3
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1
from scripts import verify_a02_long_three_arm_eval_inputs_v2_2 as v2_2


def feature_message(*, changed_id: bool = False) -> PointCloud:
    message = PointCloud()
    message.header.stamp = genpy.Time.from_sec(1.0)
    message.header.frame_id = "camera"
    message.points = [Point32(0.1, 0.2, 1.0), Point32(0.3, 0.4, 1.0)]
    values = {
        "id": [99.0 if changed_id else 10.0, 11.0],
        "camera_id": [0.0, 0.0],
        "p_u": [100.0, 200.0],
        "p_v": [50.0, 60.0],
        "velocity_x": [0.0, 0.0],
        "velocity_y": [0.0, 0.0],
        "source_code": [1.0, 2.0],
        "quality": [0.8, 0.9],
        "sigma": [1.11803398875, 1.05409255339],
    }
    message.channels = [
        ChannelFloat32(name=name, values=channel_values)
        for name, channel_values in values.items()
    ]
    return message


def write_input(path: Path) -> None:
    stamp = genpy.Time.from_sec(1.0)
    imu = Imu()
    imu.header.stamp = stamp
    imu.linear_acceleration.x = 1.25
    with rosbag.Bag(str(path), "w") as bag:
        bag.write("/imu", imu, stamp)
        bag.write("/feature_tracker/feature", feature_message(), stamp)


class ComponentContinuationV23Tests(unittest.TestCase):
    def test_incident_is_canonical_exact_and_classifies_legacy_skips(self) -> None:
        payload = v2_3.DEFAULT_INCIDENT.read_bytes()
        incident = json.loads(payload)
        self.assertEqual(payload, v1.canonical_json(incident))
        self.assertEqual(incident, v2_3.expected_incident_record())
        self.assertEqual(incident["status"], v2_3.INCIDENT_STATUS)
        for arm in ("b1_vins", "xfeat_vins"):
            record = incident["stage_observations"][arm]
            self.assertEqual(record["reported_return_code"], 125)
            self.assertEqual(record["legacy_attempt_count_field"], 1)
            self.assertEqual(record["algorithm_process_start_count"], 0)
            self.assertEqual(
                record["semantic_interpretation"],
                "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
            )

    def test_old_skip_tree_rejects_rc0_and_extra_file(self) -> None:
        expected = v1.build_vins_process_receipt("B1_CONSTQ", 125)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "process_rc_receipt.json"
            receipt.write_bytes(v1.canonical_json(expected))
            result = v2_3.old_skip_tree(root, "TEST_SKIP", "B1_CONSTQ")
            self.assertEqual(
                result["semantic_interpretation"]["classification"],
                "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
            )
            receipt.write_bytes(
                v1.canonical_json(v1.build_vins_process_receipt("B1_CONSTQ", 0))
            )
            with self.assertRaisesRegex(v1.VerificationError, "RC125_RECEIPT"):
                v2_3.old_skip_tree(root, "TEST_SKIP", "B1_CONSTQ")
            receipt.write_bytes(v1.canonical_json(expected))
            (root / "extra").write_bytes(b"not allowed")
            with self.assertRaisesRegex(v1.VerificationError, "SINGLETON"):
                v2_3.old_skip_tree(root, "TEST_SKIP", "B1_CONSTQ")

    def test_synthetic_both_sources_pass_and_source1_only_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            output = root / "output.bag"
            write_input(source)
            rewriter.rewrite_bag(
                input_bag=source,
                output_bag=output,
                feature_topic="/feature_tracker/feature",
                source_codes={1, 2},
                quality=1.0,
                min_quality=0.05,
            )
            with self.assertRaises(ValueError):
                auditor.audit_bags(
                    input_bag=source,
                    output_bag=output,
                    feature_topic="/feature_tracker/feature",
                    source_codes={1},
                    quality=1.0,
                    min_quality=0.05,
                )
            result = auditor.audit_bags(
                input_bag=source,
                output_bag=output,
                feature_topic="/feature_tracker/feature",
                source_codes={1, 2},
                quality=1.0,
                min_quality=0.05,
            )
            self.assertEqual(result["source_codes"], [1, 2])
            self.assertEqual(result["selected_observations"], 2)
            self.assertEqual(result["untouched_observations"], 0)

    def test_synthetic_topology_and_nonquality_tamper_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            output = root / "output.bag"
            write_input(source)
            stamp = genpy.Time.from_sec(1.0)
            imu = Imu()
            imu.header.stamp = stamp
            imu.linear_acceleration.x = 9.0
            with rosbag.Bag(str(output), "w") as bag:
                bag.write("/imu", imu, stamp)
                bag.write("/feature_tracker/feature", feature_message(changed_id=True), stamp)
            with self.assertRaises(ValueError):
                auditor.audit_bags(
                    input_bag=source,
                    output_bag=output,
                    feature_topic="/feature_tracker/feature",
                    source_codes={1, 2},
                    quality=1.0,
                    min_quality=0.05,
                )

    def test_exact_audit_validator_rejects_extra_source_untouched_and_hash_tamper(self) -> None:
        base = v2_3.expected_corrected_audit_claim()
        fake_identity = {
            "path": str(v2_3.CORRECTED_AUDIT),
            "size_bytes": 1,
            "sha256": "a" * 64,
        }
        with mock.patch.object(v2_3, "_ORIGINAL_LOAD", return_value=(base, fake_identity)):
            self.assertEqual(
                v2_3.validate_corrected_audit()["status"],
                "PASS_SOURCE_CODES_1_2",
            )
        mutations = (
            ("source_codes", [1, 2, 20]),
            ("untouched_observations", 1),
            ("input_sha256", "0" * 64),
            ("changed_observations", 314999),
        )
        for key, value in mutations:
            tampered = dict(base)
            tampered[key] = value
            with self.subTest(key=key), mock.patch.object(
                v2_3, "_ORIGINAL_LOAD", return_value=(tampered, fake_identity)
            ):
                with self.assertRaisesRegex(v1.VerificationError, "NOT_EXACT"):
                    v2_3.validate_corrected_audit()

    def test_real_corrected_audit_probe_is_read_only_and_exact(self) -> None:
        before = (
            hashlib.sha256(v1.DEFAULT_B1_NATIVE_BAG.read_bytes()).hexdigest(),
            hashlib.sha256(v1.DEFAULT_B1_CONSTQ_BAG.read_bytes()).hexdigest(),
        )
        result = v2_3.probe_corrected_audit_read_only()
        after = (
            hashlib.sha256(v1.DEFAULT_B1_NATIVE_BAG.read_bytes()).hexdigest(),
            hashlib.sha256(v1.DEFAULT_B1_CONSTQ_BAG.read_bytes()).hexdigest(),
        )
        self.assertEqual(before, after)
        self.assertEqual(result["selected_observations"], 315000)
        self.assertEqual(result["changed_observations"], 315000)
        self.assertEqual(result["untouched_observations"], 0)
        self.assertEqual(
            result["native_source_distribution"],
            {
                "feature_frames": 900,
                "source_code_counts": {"1": 310704, "2": 4296},
                "total_observations": 315000,
            },
        )

    def test_new_receipt_contract_distinguishes_skip_from_actual_attempt(self) -> None:
        skipped = v2_3.build_receipt_v2_3("B1_CONSTQ", 125, False)
        passed = v2_3.build_receipt_v2_3("B1_CONSTQ", 0, True)
        failed = v2_3.build_receipt_v2_3("B1_CONSTQ", 7, True)
        self.assertEqual(skipped["actual_process_start_count"], 0)
        self.assertEqual(skipped["attempt_count"], 0)
        self.assertEqual(passed["status"], "PASS_ACTUAL_PROCESS_RC0")
        self.assertEqual(failed["status"], "FAIL_ACTUAL_PROCESS_NONZERO")
        with self.assertRaisesRegex(v1.VerificationError, "MUST_BE_RC125"):
            v2_3.build_receipt_v2_3("B1_CONSTQ", 2, False)

    def test_vins_ports_match_v1_hardcoded_provenance_and_paths_are_new(self) -> None:
        self.assertEqual(v2_3.B1_PORT, 11531)
        self.assertEqual(v2_3.XFEAT_PORT, 11532)
        self.assertNotEqual(v2_3.B1_RUN, v2_3.OLD_B1_SKIP_ROOT)
        self.assertNotEqual(v2_3.XFEAT_RUN, v2_3.OLD_XFEAT_SKIP_ROOT)
        self.assertIn("post_incident_v2_3", v2_3.B1_TAG)
        self.assertIn("post_incident_v2_3", v2_3.XFEAT_TAG)

    def test_fixed_argument_injection_is_unique_and_conflict_closed(self) -> None:
        result = v2_3.injected_v1_arguments(["--action", "check"])
        for option in (
            "--b1-quality-audit", "--xfeat-bag", "--xfeat-manifest",
            "--xfeat-audit", "--b1", "--b1-log", "--xfeat",
            "--xfeat-log", "--evidence",
        ):
            self.assertEqual(result.count(option), 1)
            with self.assertRaisesRegex(v1.VerificationError, "CONFLICT"):
                v2_3.injected_v1_arguments(["--action", "check", option, "/tmp/x"])
            with self.assertRaisesRegex(v1.VerificationError, "CONFLICT"):
                v2_3.injected_v1_arguments(["--action", "check", option + "=/tmp/x"])

    def test_v1_patch_scope_restores_all_functions_and_commands(self) -> None:
        originals = (
            v1.load_canonical_json,
            v1.validate_quality_chain,
            v1.vins_process_receipt_contract,
            v1.validate_vins_process_receipt,
        )
        old_commands = json.loads(
            v2_1.DEFAULT_OLD_FREEZE.read_text(encoding="utf-8")
        )["commands"]

        def fake_build(args: object) -> dict[str, object]:
            self.assertIs(v1.load_canonical_json, v2_1.load_canonical_json_v2)
            self.assertIs(v1.validate_quality_chain, v2_3.validate_quality_chain_v2_3)
            self.assertIs(v1.vins_process_receipt_contract, v2_3.receipt_contract_v2_3)
            self.assertIs(v1.validate_vins_process_receipt, v2_3.validate_receipt_v2_3)
            self.assertEqual(v1.authoritative_commands(), old_commands)
            self.assertEqual(args.b1_quality_audit, v2_3.CORRECTED_AUDIT)
            return {"status": "FAKE"}

        with mock.patch.object(v1, "build_record", side_effect=fake_build):
            self.assertEqual(v2_3._build_component_base_record(), {"status": "FAKE"})
        self.assertEqual(
            (
                v1.load_canonical_json,
                v1.validate_quality_chain,
                v1.vins_process_receipt_contract,
                v1.validate_vins_process_receipt,
            ),
            originals,
        )
        self.assertEqual(v1.authoritative_commands(), old_commands)

    def test_commands_are_component_only_propagate_rc_and_bash_n(self) -> None:
        commands = v2_3.expected_commands()
        self.assertEqual(len(commands), 10)
        self.assertIn("--source-code 1 --source-code 2", commands[1])
        self.assertTrue(commands[1].endswith('exit "$audit_rc"'))
        self.assertIn("ROS_MASTER_URI=http://localhost:11531", commands[7])
        self.assertIn("ROS_MASTER_URI=http://localhost:11532", commands[8])
        joined = "\n".join(commands)
        for forbidden in (
            "agent_qi_calibration_rewrite_bag.py",
            "run_a02_b1_klt_nativeq_current_exporter_guarded",
            "run_hfnet_slam_a02_long1801_headless_v4.py",
            "bridge_hfnet_world_body_to_vins_csv_v1.py",
            "evaluate_vins_common_support.py",
            str(v1.DEFAULT_B1_QUALITY_AUDIT),
            str(v1.DEFAULT_XFEAT_BAG.parent),
            str(v2_3.OLD_B1_SKIP_ROOT),
            str(v2_3.OLD_XFEAT_SKIP_ROOT),
        ):
            self.assertNotIn(forbidden, joined)
        for index, command in enumerate(commands):
            checked = subprocess.run(
                ["/bin/bash", "-n"], input=command, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(checked.returncode, 0, (index, checked.stderr))

    def test_terminal_record_seals_pass_or_failure_without_ranking(self) -> None:
        carry = {
            "hfnet_run_result": {"path": "/hfnet/result", "sha256": "a" * 64, "size_bytes": 1},
            "v2_2_preseal": {"path": "/preseal", "sha256": "b" * 64, "size_bytes": 1},
        }
        base = {
            "schema_version": v1.SCHEMA,
            "status": "FAIL_ONE_OR_MORE_SCIENTIFIC_ARMS",
            "scientific_role": "old",
            "arms": {
                "B1_CONSTQ": {"status": "PASS"},
                "XFEATBIRTH_RAWLK": {"status": "PASS"},
                "HFNET_WHOLE_SYSTEM": {"status": "FAIL", "reasons": ["unusable"]},
            },
        }
        common = (
            mock.patch.object(v2_3, "validate_revision", return_value={}),
            mock.patch.object(v2_3, "current_terminal_carry_forward", return_value=carry),
            mock.patch.object(v2_3, "v2_2_preseal_recomputation", return_value={"status": "PASS"}),
            mock.patch.object(v2_3, "continuation_binding", return_value={"role": v2_3.SCIENTIFIC_ROLE}),
            mock.patch.object(v2_3, "observe_receipt", return_value={"status": "OBSERVED"}),
        )
        with common[0], common[1], common[2], common[3], common[4], mock.patch.object(
            v2_3, "_build_component_base_record", return_value=base
        ):
            passed = v2_3.build_terminal_record(Path("/freeze"))
        self.assertEqual(passed["status"], v2_3.TERMINAL_PASS)
        self.assertFalse(passed["terminal_outcome"]["component_ranking_performed"])
        failed_base = copy.deepcopy(base)
        failed_base["arms"]["XFEATBIRTH_RAWLK"] = {"status": "FAIL"}
        common2 = (
            mock.patch.object(v2_3, "validate_revision", return_value={}),
            mock.patch.object(v2_3, "current_terminal_carry_forward", return_value=carry),
            mock.patch.object(v2_3, "v2_2_preseal_recomputation", return_value={"status": "PASS"}),
            mock.patch.object(v2_3, "continuation_binding", return_value={"role": v2_3.SCIENTIFIC_ROLE}),
            mock.patch.object(v2_3, "observe_receipt", return_value={"status": "OBSERVED"}),
        )
        with common2[0], common2[1], common2[2], common2[3], common2[4], mock.patch.object(
            v2_3, "_build_component_base_record", return_value=failed_base
        ):
            failed = v2_3.build_terminal_record(Path("/freeze"))
        self.assertEqual(failed["status"], v2_3.TERMINAL_FAIL)
        self.assertTrue(failed["terminal_outcome"]["terminal_failure_sealed"])

    def test_reserved_paths_and_prior_missing_outputs_are_currently_absent(self) -> None:
        for raw in v2_3.RESERVED_PATHS:
            path = Path(raw)
            self.assertFalse(path.exists() or path.is_symlink(), raw)
        prior = json.loads(v2_2.DEFAULT_REVISION_FREEZE.read_text(encoding="utf-8"))
        for raw in v2_3.prior_absent_paths(prior):
            path = Path(raw)
            self.assertFalse(path.exists() or path.is_symlink(), raw)

    def test_prior_absent_set_never_shrinks_when_a_path_appears(self) -> None:
        prior = json.loads(v2_2.DEFAULT_REVISION_FREEZE.read_text(encoding="utf-8"))
        absent = v2_3.prior_absent_paths(prior)
        appeared = absent[0]

        def fake_exists(path: Path) -> bool:
            return str(path) == appeared

        with mock.patch.object(Path, "exists", fake_exists), mock.patch.object(
            Path, "is_symlink", return_value=False
        ):
            self.assertEqual(v2_3.prior_absent_paths(prior), absent)
            with self.assertRaisesRegex(
                v1.VerificationError, "V2_3_PRIOR_ABSENT_PATH_APPEARED"
            ):
                v2_3.require_paths_absent(
                    absent, "V2_3_PRIOR_ABSENT_PATH_APPEARED"
                )

    def test_v2_2_preseal_remains_byte_recomputable(self) -> None:
        result = v2_3.v2_2_preseal_recomputation()
        self.assertEqual(result["status"], "PASS_BYTE_RECOMPUTABLE")
        self.assertEqual(result["identity"]["sha256"], v2_3.EXPECTED_V2_2_PRESEAL_SHA256)

    def test_committed_freeze_is_canonical_exact_builder_record(self) -> None:
        from scripts import build_a02_long_component_continuation_freeze_v2_3 as builder

        if not v2_3.DEFAULT_FREEZE.exists():
            self.skipTest("freeze is created only after implementation bytes settle")
        payload = v2_3.DEFAULT_FREEZE.read_bytes()
        record = json.loads(payload)
        self.assertEqual(payload, v1.canonical_json(record))
        self.assertEqual(record, builder.build_freeze_record())
        self.assertEqual(record["commands"], v2_3.expected_commands())
        self.assertEqual(len(record["protocol_history"]), 3)

    def test_freeze_authoritative_fields_and_keyset_tamper_fail(self) -> None:
        if not v2_3.DEFAULT_FREEZE.exists():
            self.skipTest("freeze is created only after implementation bytes settle")
        base = json.loads(v2_3.DEFAULT_FREEZE.read_text(encoding="utf-8"))
        mutations = []
        extra = copy.deepcopy(base)
        extra["unauthorized"] = True
        mutations.append((extra, "SCHEMA_STATUS_CWD"))
        role = copy.deepcopy(base)
        role["post_incident_evidence_role"] = "CONFIRMATORY"
        mutations.append((role, "EVIDENCE_ROLE"))
        policy = copy.deepcopy(base)
        policy["execution_policy"]["no_retry"] = False
        mutations.append((policy, "EXECUTION_POLICY"))
        with tempfile.TemporaryDirectory() as directory:
            for index, (record, reason) in enumerate(mutations):
                path = Path(directory) / f"tampered-{index}.json"
                path.write_bytes(v1.canonical_json(record))
                with self.subTest(reason=reason), self.assertRaisesRegex(
                    v1.VerificationError, reason
                ):
                    v2_3.validate_revision(path, require_reserved_absent=False)


if __name__ == "__main__":
    unittest.main()
