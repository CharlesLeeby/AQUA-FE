#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from scripts import run_hfnet_v6_samehistory_positive_roster_accuracy_v1 as controller
from scripts import evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1 as evaluator
from scripts import build_hfnet_v6_samehistory_accuracy_prefreeze_seal_v1 as seal_builder


def write(path: Path, payload: bytes) -> controller.FileSnapshot:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return controller.snapshot_file(path.resolve(), path.name)[0]


class DecimalLoaderAndBridgeTest(unittest.TestCase):
    def test_decimal_epoch_nanoseconds_and_scientific_seconds_are_exact(self) -> None:
        self.assertEqual(
            controller.decimal_timestamp_to_ns("1455214344591163136.000000", "hfnet"),
            1_455_214_344_591_163_136,
        )
        self.assertEqual(
            controller.decimal_timestamp_to_ns("1.725639476534496069e+09", "tum"),
            1_725_639_476_534_496_069,
        )
        with self.assertRaisesRegex(controller.ControllerError, "SUBNANOSECOND"):
            controller.decimal_timestamp_to_ns("1.0000000001", "bad")

    def test_tum_vins_and_hfnet_quaternion_orders(self) -> None:
        tum = b"1.000000001 1 2 3 0.1 0.2 0.3 0.9\n1.100000001 2 3 4 0 0 0 1\n"
        stamps, positions, quaternions = controller.parse_ascii_pose_rows(
            tum, format_name="TUM", label="tum", timestamps_only=False
        )
        self.assertEqual(stamps, [1_000_000_001, 1_100_000_001])
        self.assertEqual(positions[0], [1.0, 2.0, 3.0])
        expected = np.asarray([0.1, 0.2, 0.3, 0.9])
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(quaternions[0], expected)

        vins = (
            b"1000000000000000000,1,2,3,0.9,0.1,0.2,0.3,7,8\n"
            b"1000000000100000000,2,3,4,1,0,0,0,7,8\n"
        )
        stamps, _positions, quaternions = controller.parse_ascii_pose_rows(
            vins, format_name="VINS_QWXYZ_CSV", label="vins", timestamps_only=False
        )
        self.assertEqual(stamps[-1] - stamps[0], 100_000_000)
        expected = np.asarray([0.1, 0.2, 0.3, 0.9])
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(quaternions[0], expected)

        hfnet = (
            b"1000000000000000000.000000 1 2 3 0.1 0.2 0.3 0.9\n"
            b"1000000000100000000.000000 2 3 4 0 0 0 1\n"
        )
        stamps, _positions, _quaternions = controller.parse_ascii_pose_rows(
            hfnet,
            format_name="HFNET_QXYZW_FLOAT_EPOCH",
            label="hfnet",
            timestamps_only=False,
        )
        self.assertEqual(stamps[-1] - stamps[0], 100_000_000)

    def test_bridge_is_unique_bijective_and_fixed_at_256ns(self) -> None:
        mapped, rows = controller.bridge_hfnet_timestamps(
            [1_000_000_100, 2_000_000_256], [1_000_000_000, 2_000_000_000]
        )
        self.assertEqual(mapped, [1_000_000_000, 2_000_000_000])
        self.assertEqual(rows[-1]["absolute_delta_ns"], 256)
        with self.assertRaisesRegex(controller.ControllerError, "GT_256NS"):
            controller.bridge_hfnet_timestamps(
                [1_000_000_257], [1_000_000_000]
            )
        with self.assertRaisesRegex(controller.ControllerError, "HEADER_REUSED"):
            controller.bridge_hfnet_timestamps(
                [1_000_000_000, 1_000_000_100],
                [1_000_000_000, 2_000_000_000],
            )

    def test_timestamp_only_parser_does_not_convert_coordinate_tokens(self) -> None:
        payload = (
            b"1000000000000000000.000000 NOT_A_COORDINATE x y q x y z\n"
            b"1000000000100000000.000000 STILL_NOT x y q x y z\n"
        )
        stamps, positions, quaternions = controller.parse_ascii_pose_rows(
            payload,
            format_name="HFNET_QXYZW_FLOAT_EPOCH",
            label="timestamps_only",
            timestamps_only=True,
        )
        self.assertEqual(len(stamps), 2)
        self.assertEqual(positions, [])
        self.assertEqual(quaternions, [])

    def test_rosbag_timestamp_gate_reads_raw_header_without_coordinates(self) -> None:
        rows = [
            ("/odom", ("nav_msgs/Odometry", struct.pack("<III", 1, 10, 20) + b"coordinates-never-decoded"), None),
            ("/odom", ("nav_msgs/Odometry", struct.pack("<III", 2, 10, 100_000_020) + b"coordinates-never-decoded"), None),
        ]

        class FakeBag:
            def __init__(self, _path, _mode):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read_messages(self, *, topics, raw=False):
                self.assert_raw = raw
                if not raw:
                    raise AssertionError("coordinate-deserializing path was used")
                self.topics = topics
                return iter(rows)

        fake_rosbag = SimpleNamespace(Bag=FakeBag)
        with mock.patch.dict(sys.modules, {"rosbag": fake_rosbag}):
            stamps, positions, quaternions = controller.load_rosbag_odometry(
                Path("/synthetic/not-opened-by-fake.bag"),
                "/odom",
                timestamps_only=True,
            )
        self.assertEqual(stamps, [10_000_000_020, 10_100_000_020])
        self.assertEqual(positions, [])
        self.assertEqual(quaternions, [])


class AtomicAndIdentityTest(unittest.TestCase):
    def test_atomic_hardlink_publication_never_clobbers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            root = Path(temporary).resolve()
            target = root / "receipt.json"
            first = controller.atomic_publish_noreplace(target, b"first\n")
            self.assertEqual(first.sha256, controller.sha256_bytes(b"first\n"))
            with self.assertRaisesRegex(controller.ControllerError, "PUBLICATION_EXISTS"):
                controller.atomic_publish_noreplace(target, b"second\n")
            self.assertEqual(target.read_bytes(), b"first\n")
            self.assertEqual(list(root.glob(".*.tmp-*")), [])

    def test_canonical_path_alias_is_rejected_before_distinctness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            root = Path(temporary).resolve()
            alias = root / "child" / ".." / "same.json"
            with self.assertRaisesRegex(controller.ControllerError, "PATH_NOT_CANONICAL"):
                controller.require_distinct_canonical_paths(
                    {"left": root / "same.json", "right": alias}
                )
            (root / "real").mkdir()
            (root / "alias").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(controller.ControllerError, "PATH_NOT_CANONICAL"):
                controller.require_distinct_canonical_paths(
                    {"left": root / "real" / "a", "right": root / "alias" / "b"}
                )

    def test_toctou_rehash_detects_same_path_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            path = Path(temporary).resolve() / "input.bin"
            before = write(path, b"AAAA")
            ledger = controller.IdentityLedger()
            ledger.add("input", before)
            path.write_bytes(b"BBBB")
            with self.assertRaisesRegex(controller.ControllerError, "TOCTOU_DETECTED"):
                ledger.verify_all()

    def test_self_identity_pin_is_content_not_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            path = Path(temporary).resolve() / "controller.py"
            observed = write(path, b"print('sealed')\n")
            wrong = dict(observed.identity)
            wrong["sha256"] = "0" * 64
            with self.assertRaisesRegex(controller.ControllerError, "IDENTITY_MISMATCH"):
                controller.verify_pinned_file(wrong, "synthetic_controller_self")

    def test_controller_built_lock_mints_only_opaque_evaluator_token(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            root = Path(temporary).resolve()
            seal_snapshot = write(root / "seal.json", b"{}\n")
            evidence = write(root / "evidence.bin", b"synthetic\n")
            controller_snapshot = controller.snapshot_file(
                controller.CONTROLLER, "controller"
            )[0]
            evaluator_snapshot = controller.snapshot_file(
                controller.EVALUATOR, "evaluator"
            )[0]
            seal = {
                "analysis_code_identities": {
                    "formal_accuracy_controller": controller_snapshot.identity,
                    "roster_evaluator_core": evaluator_snapshot.identity,
                },
                "analysis_contract": {"frame_contract": {"NTNU": {}}},
                "evo_environment": {
                    "evo_ape": dict(evaluator.EVO_APE_IDENTITY),
                    "evo_rpe": dict(evaluator.EVO_RPE_IDENTITY),
                },
            }
            row = {
                "case_id": "mclab1_s60_d15",
                "dataset": "NTNU",
                "structural_na_reasons": [],
                "historical_sources": {
                    "reference": {
                        "trajectory_or_container": evidence.identity,
                        "format": "TUM",
                        "topic": None,
                    },
                    "learned_plus_klt": {
                        "trajectory": evidence.identity,
                        "authorized_as_future_metric_input": True,
                    },
                    "klt": {
                        "trajectory": evidence.identity,
                        "authorized_as_future_metric_input": True,
                    },
                },
                "native_reference_sensitivity": {
                    "required": False,
                    "expected_native_anchor_count": None,
                    "descriptive_only": None,
                    "run_only_after_primary_gate": None,
                },
                "future_accuracy_publication": {
                    "output_dir": str(root / "published" / "attempt_001"),
                    "process_claim": str(root / "claims" / "case.start_once"),
                    "terminal_receipt": str(root / "published" / "terminal.json"),
                    "retry_permitted": False,
                    "replacement_output_permitted": False,
                    "maximum_claims": 1,
                },
            }
            lock = controller.build_execution_lock(
                seal=seal,
                seal_snapshot=seal_snapshot,
                row=row,
                evaluator=evaluator,
                runability_receipt_identity=evidence.identity,
                hfnet_trajectory_identity=evidence.identity,
                bridge_identity=evidence.identity,
                score_headers_identity=evidence.identity,
            )
            verification = evaluator.FormalIdentityVerification(
                verification_receipt_identity=evidence.identity,
                execution_lock_value_sha256=controller.sha256_bytes(
                    controller.canonical_json_bytes(lock)
                ),
                execution_lock_file_identity_verified=True,
                evaluator_self_identity_verified=True,
                controller_self_identity_verified=True,
                evidence_identities_verified=True,
                pre_metric_toctou_verified=True,
            )
            token = evaluator.validate_future_execution_lock(lock, verification)
            self.assertIsInstance(token, evaluator.ValidatedExecutionLock)
            self.assertEqual(token.case_id, "mclab1_s60_d15")
            with self.assertRaisesRegex(evaluator.ContractError, "VALIDATED_EXECUTION_LOCK_REQUIRED"):
                evaluator.evaluate_case(
                    "mclab1_s60_d15", {}, lock  # type: ignore[arg-type]
                )

    def test_only_canonical_complete_prestart_seal_is_authorized(self) -> None:
        clean = seal_builder.dry_run_document()
        self.assertEqual(
            controller.prestart_seal_semantic_projection_sha256(clean),
            controller.PRESTART_SEAL_SEMANTIC_PROJECTION_SHA256,
        )
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-seal-test-") as temporary:
            root = Path(temporary).resolve()
            canonical = root / "canonical-seal.json"
            clean_snapshot = write(canonical, controller.canonical_json_bytes(clean))
            with mock.patch.object(controller, "DEFAULT_PREFREEZE_SEAL", canonical):
                controller.verify_prestart_seal(
                    clean, clean_snapshot, require_pristine_destinations=False
                )

            tampered = json.loads(controller.canonical_json_bytes(clean))
            tampered["analysis_contract"]["gates"]["minimum_common_grid_poses"] = 1
            tampered["cases"][0]["future_accuracy_publication"]["output_dir"] = (
                "/tmp/attacker-selected-accuracy-output"
            )
            tampered["reporting_boundary"] = "TAMPERED"
            tampered_path = root / "tampered-seal.json"
            tampered_snapshot = write(
                tampered_path, controller.canonical_json_bytes(tampered)
            )
            with mock.patch.object(
                controller, "DEFAULT_PREFREEZE_SEAL", tampered_path
            ), self.assertRaisesRegex(
                controller.ControllerError,
                "PRESTART_SEAL_SEMANTIC_PROJECTION_MISMATCH",
            ):
                controller.verify_prestart_seal(
                    tampered,
                    tampered_snapshot,
                    require_pristine_destinations=False,
                )

            substitute = root / "substitute-seal.json"
            substitute_snapshot = write(
                substitute, controller.canonical_json_bytes(clean)
            )
            with self.assertRaisesRegex(
                controller.ControllerError, "PRESTART_SEAL_NONCANONICAL_PATH"
            ):
                controller.verify_prestart_seal(
                    clean,
                    substitute_snapshot,
                    require_pristine_destinations=False,
                )

            wrong_self = json.loads(controller.canonical_json_bytes(clean))
            wrong_self["analysis_code_identities"]["formal_accuracy_controller"][
                "sha256"
            ] = "0" * 64
            wrong_self_path = root / "wrong-self-seal.json"
            wrong_self_snapshot = write(
                wrong_self_path, controller.canonical_json_bytes(wrong_self)
            )
            with mock.patch.object(
                controller, "DEFAULT_PREFREEZE_SEAL", wrong_self_path
            ), self.assertRaisesRegex(
                controller.ControllerError, "CONTROLLER_SELF_IDENTITY_MISMATCH"
            ):
                controller.verify_prestart_seal(
                    wrong_self,
                    wrong_self_snapshot,
                    require_pristine_destinations=False,
                )


class EvoAdapterTest(unittest.TestCase):
    def test_exact_ape_and_rpe_commands_forbid_scale_and_rpe_alignment(self) -> None:
        ape = controller.build_evo_ape_argv(
            Path("/sealed/evo_ape"), Path("/tmp/ref.tum"), Path("/tmp/est.tum")
        )
        rpe = controller.build_evo_rpe_argv(
            Path("/sealed/evo_rpe"), Path("/tmp/ref.tum"), Path("/tmp/est.tum")
        )
        controller.validate_evo_argv(ape, "APE")
        controller.validate_evo_argv(rpe, "RPE")
        self.assertIn("-a", ape)
        self.assertNotIn("-a", rpe)
        self.assertNotIn("-s", ape)
        self.assertNotIn("-s", rpe)
        self.assertEqual(rpe[rpe.index("-d") + 1], "10")
        self.assertEqual(rpe[rpe.index("-u") + 1], "f")
        self.assertIn("--all_pairs", rpe)
        self.assertIn("--pairs_from_reference", rpe)
        self.assertEqual(ape[ape.index("--t_max_diff") + 1], "1e-9")
        self.assertEqual(rpe[rpe.index("--t_offset") + 1], "0")

    def test_evo_stdout_scalar_and_pair_count_must_be_process_output(self) -> None:
        payload = b"Compared 21 relative pose pairs.\nrmse\t0.0125\n"
        rmse, pairs = controller.parse_evo_stdout(
            payload, expected_pair_count=21, label="synthetic"
        )
        self.assertEqual(rmse, 0.0125)
        self.assertEqual(pairs, 21)
        with self.assertRaisesRegex(controller.ControllerError, "PAIR_COUNT_MISMATCH"):
            controller.parse_evo_stdout(
                payload, expected_pair_count=20, label="synthetic"
            )

    def test_materialized_tum_keeps_real_orientation_and_exact_populations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            output = Path(temporary).resolve() / "attempt"
            output.mkdir()
            timestamps = [1_000_000_000 + index * 100_000_000 for index in range(12)]
            positions = np.column_stack(
                (np.arange(12, dtype=float), np.zeros(12), np.zeros(12))
            )
            quaternions = np.tile([0.0, 0.0, 0.7071067811865475, 0.7071067811865476], (12, 1))
            material = {
                "common_stamps_ns": timestamps,
                "segments": [list(range(12))],
                "full_poses": {
                    name: {
                        "positions": positions.copy(),
                        "quaternions_xyzw": quaternions.copy(),
                    }
                    for name in controller.SOURCE_ORDER
                },
            }
            result = controller.materialize_evo_inputs(material, output)
            self.assertEqual(result["population"]["common_pose_count"], 12)
            self.assertEqual(result["population"]["exact_1s_pair_count"], 2)
            line = Path(result["all_tum"]["reference"].path).read_text().splitlines()[0]
            self.assertIn("0.707106781186547", line)
            self.assertEqual(len(line.split()), 8)

    def test_exact_evaluator_plan_is_published_executed_and_revalidated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            output = Path(temporary).resolve() / "evo"
            grid = evaluator.make_case_grid_ns("a05_3300_3700")
            timestamps = {name: grid.copy() for name in evaluator.SOURCE_ORDER}
            support = evaluator.build_common_support(
                "a05_3300_3700", timestamps, "PASS"
            )
            positions = np.column_stack(
                (
                    np.arange(len(grid), dtype=float) * 0.1,
                    np.sin(np.arange(len(grid), dtype=float) / 10.0),
                    np.zeros(len(grid)),
                )
            )
            quaternions = np.tile(
                [0.0, 0.0, 0.25881904510252074, 0.9659258262890683],
                (len(grid), 1),
            )
            bundle = evaluator.CommonFullPoseBundle(
                case_id="a05_3300_3700",
                execution_lock_value_sha256="f" * 64,
                grid_ns=np.array(grid, copy=True),
                joint_mask=np.array(support.joint_mask, copy=True),
                segment_ids=np.array(support.segment_ids, copy=True),
                rpe_pair_indices=np.array(support.rpe_pair_indices, copy=True),
                positions={
                    name: np.array(positions, copy=True)
                    for name in evaluator.SOURCE_ORDER
                },
                quaternions_xyzw={
                    name: np.array(quaternions, copy=True)
                    for name in evaluator.SOURCE_ORDER
                },
                transform_audit={},
            )
            plan = evaluator.plan_evo_adapter(support, bundle, output)
            primary = {
                "case_id": "a05_3300_3700",
                "accuracy_status": "PRIMARY_METRICS_COMPUTED_EVO_PENDING",
                "execution_lock_binding": {"value_sha256": "f" * 64},
                "evo_population_contract": evaluator.evo_population_contract(support),
                "independent_evo_pending": {
                    "status": "EVO_CROSSCHECK_PENDING",
                    "plan_core_sha256": plan.document["plan_core_sha256"]
                },
                "claim_boundary": {
                    "accuracy_numeric_authorized": False,
                    "ranking_authorized": False,
                },
                "metrics": {
                    arm: {
                        "translation_ape": {"rmse_m": 0.0},
                        "translation_rpe_exact_1s": {"rmse_m": 0.0},
                    }
                    for arm in evaluator.ESTIMATE_ORDER
                },
            }
            context = SimpleNamespace(
                evaluator=evaluator,
                case_id="a05_3300_3700",
            )
            fake_process = SimpleNamespace(
                stdout=b"rmse 0.0\n", stderr=b"", returncode=0
            )
            with mock.patch.object(
                controller.subprocess, "run", return_value=fake_process
            ) as invoked:
                result = controller.execute_evaluator_evo_plan(
                    context, primary, plan, output
                )
            self.assertEqual(invoked.call_count, 6)
            self.assertEqual(result["crosscheck"]["status"], "PASS")
            self.assertEqual(len(result["receipt"]["commands"]), 6)
            for command in result["receipt"]["commands"]:
                self.assertNotIn("-s", command["argv"])
                if command["command_id"].startswith("rpe:"):
                    self.assertNotIn("-a", command["argv"])


class ExactlyOnceTerminalTest(unittest.TestCase):
    def test_claim_recovers_post_link_exception_as_consumed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            target = Path(temporary).resolve() / "claim.json"
            value = {"status": "claimed"}
            real_publish = controller.atomic_publish_noreplace

            def publish_then_raise(path, payload, mode=0o444):
                real_publish(path, payload, mode)
                raise OSError("synthetic directory fsync uncertainty")

            with mock.patch.object(
                controller, "atomic_publish_noreplace", side_effect=publish_then_raise
            ):
                observed, error = controller.take_exactly_once_claim(target, value)
            self.assertIsInstance(error, OSError)
            self.assertEqual(observed.identity, controller.snapshot_file(target, "claim")[0].identity)
            self.assertEqual(
                target.read_bytes(), controller.canonical_json_bytes(value)
            )

    def test_failure_after_claim_still_has_one_terminal_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqua-accuracy-test-") as temporary:
            root = Path(temporary).resolve()
            input_snapshot = write(root / "scientific-input.bin", b"sealed\n")
            lock_snapshot = write(root / "execution-lock.json", b"{}\n")
            controller_snapshot = write(root / "controller.py", b"controller\n")
            evaluator_snapshot = write(root / "evaluator.py", b"evaluator\n")
            seal_snapshot = write(root / "seal.json", b"{}\n")
            ledger = controller.IdentityLedger()
            ledger.add("scientific", input_snapshot)
            case_root = root / "publication" / "case"
            claim = root / "publication" / "_claims" / "case.start_once"
            terminal = case_root / "terminal_receipt.json"
            output = case_root / "attempt_001"
            lock = {
                "case_id": "a05_3300_3700",
                "hfnet_runability_receipt": {
                    "identity": input_snapshot.identity,
                    "status": "PASS",
                },
                "frame_convention_seal": seal_snapshot.identity,
                "sources": {
                    "hfnet": {
                        "timestamp_contract": {
                            "bridge_receipt": input_snapshot.identity
                        }
                    }
                },
            }
            runability = {
                "case_id": "a05_3300_3700",
                "status": "PASS_SAMEHISTORY_COLDSTART_RUNABILITY",
                "terminal_contract": {
                    "attempt_consumed": True,
                    "retry_after_pass_or_fail": False,
                },
            }
            context = controller.VerifiedContext(
                case_id="a05_3300_3700",
                execution_lock=lock,
                execution_lock_snapshot=lock_snapshot,
                seal={},
                seal_snapshot=seal_snapshot,
                row={},
                evaluator=object(),
                evaluator_snapshot=evaluator_snapshot,
                controller_snapshot=controller_snapshot,
                ledger=ledger,
                destinations={
                    "output_dir": output,
                    "process_claim": claim,
                    "terminal_receipt": terminal,
                },
                runability_receipt=runability,
                bridge_receipt={},
            )

            @contextlib.contextmanager
            def fake_locked(_path):
                yield lock, lock_snapshot

            with mock.patch.object(controller, "locked_execution_lock", fake_locked), mock.patch.object(
                controller, "verify_execution_context", return_value=context
            ), mock.patch.object(
                controller,
                "_mint_validated_lock",
                side_effect=controller.ControllerError("SYNTHETIC_AFTER_CLAIM_FAILURE"),
            ):
                result = controller.run_case(
                    "a05_3300_3700",
                    root / "execution-lock.json",
                    controller.AUTHORIZATION_TOKEN,
                )
            self.assertTrue(claim.is_file())
            self.assertTrue(terminal.is_file())
            self.assertEqual(result["status"], "CLOSED_TERMINAL_FAILURE_NO_RETRY")
            self.assertEqual(result["failure_code"], "SYNTHETIC_AFTER_CLAIM_FAILURE")
            terminal_value = json.loads(terminal.read_text())
            self.assertTrue(terminal_value["terminal_contract"]["attempt_consumed"])
            self.assertFalse(terminal_value["terminal_contract"]["retry_permitted"])
            with self.assertRaisesRegex(controller.ControllerError, "PUBLICATION_EXISTS"):
                controller.atomic_publish_noreplace(
                    terminal, controller.canonical_json_bytes({"replacement": True})
                )


if __name__ == "__main__":
    unittest.main()
