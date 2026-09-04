#!/usr/bin/env python3

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_samehistory_positive_roster_v1 as subject


class FrozenFixture:
    def __init__(self, root: Path, case_id: str = "case_a") -> None:
        self.source_root = root
        self.source_root.mkdir(parents=True)
        self.case_id = case_id
        self.input_root = root / "input"
        self.input_root.mkdir()
        self.images = self.input_root / "mav0/cam0/data"
        self.images.mkdir(parents=True)
        self.imu = self.input_root / "mav0/imu0/data.csv"
        self.imu.parent.mkdir(parents=True)
        self.stamps = [1_000 + index * 100 for index in range(30)]
        (self.input_root / "cam0_times.txt").write_text(
            "\n".join(str(value) for value in self.stamps) + "\n",
            encoding="ascii",
        )
        for stamp in self.stamps:
            (self.images / f"{stamp}.png").write_bytes(
                b"png-" + str(stamp).encode()
            )
        imu_stamps = [900] + list(range(1_100, 4_000, 100)) + [4_000]
        self.imu.write_text(
            "#timestamp [ns],w_x,w_y,w_z,a_x,a_y,a_z\n"
            + "\n".join(f"{value},0,0,0,0,0,0" for value in imu_stamps)
            + "\n",
            encoding="ascii",
        )
        self.manifest = self.input_root / "materialization_manifest.json"
        self.manifest.write_text('{"status":"FROZEN"}\n', encoding="utf-8")
        self.config = root / "config.yaml"
        self.config.write_text(
            "%YAML:1.0\n" + subject.MODEL_PATH_LINE + "\nCamera.fps: 5.0\n",
            encoding="utf-8",
        )
        self.audit = root / "input_audit.json"
        self.publication_pointer = subject.PUBLICATION_POINTER
        self.spec: dict[str, object] = {
            "schema_version": subject.CASE_SCHEMA,
            "status": "FROZEN_READY_FOR_ONE_SHOT_COLDSTART",
            "case_id": case_id,
            "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
            "camera_count": len(self.stamps),
            "camera_header_ns_inclusive": [self.stamps[0], self.stamps[-1]],
            "score_relative_indices_inclusive": [0, len(self.stamps) - 1],
            "input_root": str(self.input_root),
            "times_relative_path": "cam0_times.txt",
            "images_relative_path": "mav0/cam0/data",
            "image_extension": ".png",
            "imu_relative_path": "mav0/imu0/data.csv",
            "attempt_root": str(subject.canonical_attempt_root(case_id)),
            "timeout_seconds": 60,
            "authorization_token": "A" * 40,
            "retry_permitted": False,
            "accuracy_evaluated_by_runner": False,
            "input_manifest": subject.identity(self.manifest),
            "base_config": subject.identity(self.config),
        }
        binding = subject.expected_input_audit_binding(
            self.spec,
            self.input_root,
            self.spec["input_manifest"],
            self.spec["base_config"],
        )
        audit_schema = "fixture-independent-input-audit-v1"
        self.audit.write_text(
            json.dumps(
                {
                    "schema_version": audit_schema,
                    "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
                    "claims": {
                        "hfnet_started": False,
                        "trajectory_produced": False,
                    },
                    "runner_binding": binding,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.spec["input_audit"] = {
            **subject.identity(self.audit),
            "schema_version": audit_schema,
        }
        self.write_lock()
        self.write_spec()
        self.write_pointer()

    def write_lock(self, *, core_digest: str | None = None) -> None:
        digest = core_digest or subject.core_spec_sha256(self.spec)
        payload = subject.canonical_json(
            {
                "schema_version": subject.ROSTER_LOCK_SCHEMA,
                "status": "FROZEN_READY_FOR_EXECUTION",
                "case_count": 1,
                "cases": [
                    {
                        "case_id": self.case_id,
                        "core_spec_sha256": digest,
                        "attempt_root": str(
                            subject.canonical_attempt_root(self.case_id)
                        ),
                    }
                ],
            }
        )
        next_root = self.publication_pointer.parent / (
            f".{self.publication_pointer.stem}.bundle-"
            f"{subject.sha256_bytes(payload)[:16]}"
        )
        old_root = getattr(self, "root", None)
        if old_root is not None and old_root != next_root and old_root.exists():
            shutil.rmtree(old_root)
        self.root = next_root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "cases").mkdir(exist_ok=True)
        self.roster_lock = self.root / "roster_lock.json"
        self.spec_path = self.root / "cases" / f"{self.case_id}.json"
        self.build_receipt = self.root / "build_receipt.json"
        self.roster_lock.write_bytes(payload)
        self.spec["roster_lock"] = subject.identity(self.roster_lock)

    def write_spec(self) -> None:
        self.spec_path.write_text(
            json.dumps(self.spec, sort_keys=True) + "\n", encoding="utf-8"
        )

    def write_pointer(self) -> None:
        roster_identity = {
            key: self.spec["roster_lock"][key]
            for key in ("path", "size_bytes", "sha256")
        }
        cases = [
            {
                "case_id": self.case_id,
                "spec": subject.identity(self.spec_path),
                "core_spec_sha256": subject.core_spec_sha256(self.spec),
            }
        ]
        claims = {"hfnet_started": False}
        self.build_receipt.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "aqua-fe-hfnet-v6-samehistory-roster-build-receipt-v1"
                    ),
                    "status": "FROZEN_READY_FOR_EXECUTION",
                    "roster_lock": roster_identity,
                    "cases": cases,
                    "claims": claims,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        pointer = {
            "schema_version": subject.PUBLICATION_POINTER_SCHEMA,
            "status": "FROZEN_READY_FOR_EXECUTION",
            "bundle_root": str(self.roster_lock.parent.resolve()),
            "roster_lock": roster_identity,
            "build_receipt": subject.identity(self.build_receipt),
            "cases": cases,
            "claims": claims,
        }
        self.publication_pointer.parent.mkdir(parents=True, exist_ok=True)
        self.publication_pointer.write_text(
            json.dumps(pointer, sort_keys=True) + "\n", encoding="utf-8"
        )

    def update_audit(self, mutate: object) -> None:
        value = json.loads(self.audit.read_text(encoding="utf-8"))
        mutate(value)
        self.audit.write_text(
            json.dumps(value, sort_keys=True) + "\n", encoding="utf-8"
        )
        schema = self.spec["input_audit"]["schema_version"]
        self.spec["input_audit"] = {
            **subject.identity(self.audit),
            "schema_version": schema,
        }
        self.write_lock()
        self.write_spec()
        self.write_pointer()

    def materialize_prepared(self, stack: dict[str, object]) -> dict[str, object]:
        paths = subject.attempt_paths(self.spec)
        paths["result_dir"].mkdir(parents=True)
        paths["local_model"].parent.mkdir(parents=True)
        paths["local_model"].write_bytes(b"onnx")
        paths["local_cache"].write_bytes(b"cache")
        paths["runtime_config"].write_bytes(
            subject.runtime_config_bytes(self.config, paths["local_model"])
        )
        prepared = {
            "schema_version": subject.PREPARED_SCHEMA,
            "status": "PREPARED_NOT_STARTED",
            "prepared_at_utc": "2026-08-29T00:00:00+00:00",
            "case_id": self.case_id,
            "case_spec": subject.identity(self.spec_path),
            "runner": subject.identity(subject.RUNNER),
            "stack": stack,
            "frozen_dependencies": subject.require_frozen_dependencies(
                self.spec_path, self.spec, self.input_root
            ),
            "input_inventory": subject.input_inventory(self.spec, self.stamps),
            "derived": subject.canonical_derived(self.spec, paths),
            "launch": subject.canonical_launch(self.spec, paths),
            "scientific_boundary": subject.canonical_scientific_boundary(self.spec),
        }
        paths["prepared"].write_bytes(subject.canonical_json(prepared))
        return prepared


class SameHistoryRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.roster_patch = mock.patch.object(
            subject, "ROSTER_ROOT", self.root / "roster"
        )
        self.size_patch = mock.patch.object(subject, "EXPECTED_ROSTER_SIZE", 1)
        self.pointer_patch = mock.patch.object(
            subject, "PUBLICATION_POINTER", self.root / "publication_pointer.json"
        )
        self.roster_patch.start()
        self.size_patch.start()
        self.pointer_patch.start()

    def tearDown(self) -> None:
        self.pointer_patch.stop()
        self.size_patch.stop()
        self.roster_patch.stop()
        self.directory.cleanup()

    def fixture(self) -> FrozenFixture:
        return FrozenFixture(self.root / "fixture")

    def fake_stack(self) -> tuple[dict[str, object], object]:
        stack = {"fixture": True}
        sizes = {
            "binary": (1, "1" * 64),
            "official_library": (1, "2" * 64),
            "onnx": (4, subject.sha256_bytes(b"onnx")),
            "cache": (5, subject.sha256_bytes(b"cache")),
        }
        patcher = mock.patch.multiple(
            subject,
            EXPECTED_STACK=sizes,
            require_stack=mock.Mock(return_value=stack),
        )
        return stack, patcher

    def test_runtime_config_changes_only_model_path(self) -> None:
        fixture = self.fixture()
        output = subject.runtime_config_bytes(
            fixture.config, self.root / "attempt/model/HF-Net.onnx"
        ).decode("utf-8")
        self.assertNotIn(subject.MODEL_PATH_LINE, output)
        self.assertIn(f'Extractor.modelPath: "{self.root}/attempt/model/"', output)
        self.assertIn("Camera.fps: 5.0", output)

    def test_input_inventory_accepts_padded_official_reader_brackets(self) -> None:
        fixture = self.fixture()
        imu_stamps = list(range(0, 5_001, 50))
        fixture.imu.write_text(
            "#timestamp [ns],w_x,w_y,w_z,a_x,a_y,a_z\n"
            + "\n".join(f"{value},0,0,0,0,0,0" for value in imu_stamps)
            + "\n",
            encoding="ascii",
        )

        inventory = subject.input_inventory(fixture.spec, fixture.stamps)

        self.assertTrue(inventory["imu_reader_bracket_valid"])
        self.assertEqual(
            inventory["imu_reader_bracket"],
            {
                "first_camera_ns": 1_000,
                "first_camera_predecessor_imu_ns": 1_000,
                "first_camera_successor_imu_ns": 1_050,
                "last_camera_ns": 3_900,
                "last_camera_predecessor_imu_ns": 3_900,
                "last_camera_successor_imu_ns": 3_950,
            },
        )

    def test_input_inventory_rejects_missing_reader_endpoint_bracket(self) -> None:
        fixture = self.fixture()
        invalid_rows = {
            "predecessor": list(range(1_050, 5_001, 50)),
            "successor": list(range(0, 3_901, 50)),
        }
        for label, imu_stamps in invalid_rows.items():
            with self.subTest(label=label):
                fixture.imu.write_text(
                    "#timestamp [ns],w_x,w_y,w_z,a_x,a_y,a_z\n"
                    + "\n".join(
                        f"{value},0,0,0,0,0,0" for value in imu_stamps
                    )
                    + "\n",
                    encoding="ascii",
                )
                with self.assertRaisesRegex(
                    subject.ContractError, "IMU_READER_BRACKET_INVALID"
                ):
                    subject.input_inventory(fixture.spec, fixture.stamps)

    def test_parse_trajectory_selects_earliest_longest_run(self) -> None:
        path = self.root / "trajectory.txt"
        stamps = [1_000 + index * 50 for index in range(12)]
        selected = stamps[1:5] + stamps[7:11]
        path.write_text(
            "\n".join(f"{stamp} 0 0 0 0 0 0 1" for stamp in selected) + "\n",
            encoding="ascii",
        )
        value = subject.parse_trajectory(path, stamps)
        self.assertTrue(value["valid"])
        self.assertEqual(
            value["longest_contiguous_relative_indices_inclusive"], [1, 4]
        )

    def test_audit_binding_and_schema_are_exact(self) -> None:
        fixture = self.fixture()
        dependencies = subject.require_frozen_dependencies(
            fixture.spec_path, fixture.spec, fixture.input_root
        )
        self.assertEqual(
            dependencies["input_audit"]["runner_binding"]["schema_version"],
            subject.AUDIT_BINDING_SCHEMA,
        )
        self.assertEqual(
            dependencies["publication_pointer"][
                "selected_case_core_spec_sha256"
            ],
            subject.core_spec_sha256(fixture.spec),
        )
        fixture.update_audit(
            lambda value: value["runner_binding"].__setitem__("camera_count", 999)
        )
        with self.assertRaisesRegex(
            subject.ContractError, "INPUT_AUDIT_RUNNER_BINDING_MISMATCH"
        ):
            subject.require_frozen_dependencies(
                fixture.spec_path, fixture.spec, fixture.input_root
            )

    def test_audit_top_level_schema_must_match_spec_pin(self) -> None:
        fixture = self.fixture()
        value = json.loads(fixture.audit.read_text(encoding="utf-8"))
        value["schema_version"] = "different-audit-v1"
        fixture.audit.write_text(json.dumps(value) + "\n", encoding="utf-8")
        old_schema = fixture.spec["input_audit"]["schema_version"]
        fixture.spec["input_audit"] = {
            **subject.identity(fixture.audit),
            "schema_version": old_schema,
        }
        fixture.write_lock()
        fixture.write_spec()
        with self.assertRaisesRegex(
            subject.ContractError, "INPUT_AUDIT_SCHEMA_MISMATCH"
        ):
            subject.require_frozen_dependencies(
                fixture.spec_path, fixture.spec, fixture.input_root
            )

    def test_roster_lock_binds_core_spec_and_canonical_attempt(self) -> None:
        fixture = self.fixture()
        subject.require_roster_lock(fixture.spec)
        fixture.spec["timeout_seconds"] = 61
        fixture.write_spec()
        with self.assertRaisesRegex(
            subject.ContractError, "ROSTER_LOCK_CORE_SPEC_MISMATCH"
        ):
            subject.require_roster_lock(fixture.spec)
        fixture.spec["attempt_root"] = str(self.root / "attempt_002")
        with self.assertRaisesRegex(
            subject.ContractError, "ROSTER_LOCK_CASE_ATTEMPT_MISMATCH"
        ):
            subject.require_roster_lock(fixture.spec)

    def test_hidden_bundle_spec_is_rejected_without_canonical_pointer(self) -> None:
        fixture = self.fixture()
        fixture.publication_pointer.unlink()
        with self.assertRaisesRegex(
            subject.ContractError, "NOT_REGULAR_NONSYMLINK_FILE"
        ):
            subject.validate_spec(fixture.spec_path)

    def test_pointer_must_pin_current_case_spec_identity(self) -> None:
        fixture = self.fixture()
        pointer = json.loads(
            fixture.publication_pointer.read_text(encoding="utf-8")
        )
        pointer["cases"][0]["spec"]["sha256"] = "0" * 64
        fixture.publication_pointer.write_text(
            json.dumps(pointer) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            subject.ContractError,
            "PUBLICATION_POINTER_CASE_SPEC_IDENTITY_MISMATCH",
        ):
            subject.validate_spec(fixture.spec_path)

    def test_pointer_rejects_tampered_bundle_name(self) -> None:
        fixture = self.fixture()
        pointer = json.loads(
            fixture.publication_pointer.read_text(encoding="utf-8")
        )
        pointer["bundle_root"] = str(
            fixture.publication_pointer.parent / ".noncanonical-bundle"
        )
        fixture.publication_pointer.write_text(
            json.dumps(pointer) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            subject.ContractError,
            "PUBLICATION_POINTER_NONCANONICAL_BUNDLE_NAME",
        ):
            subject.validate_spec(fixture.spec_path)

    def test_one_real_plus_nine_dummy_pointer_rows_are_rejected(self) -> None:
        fixture = self.fixture()
        dummy_ids = [f"dummy_{index}" for index in range(9)]
        roster_rows = [
            {
                "case_id": fixture.case_id,
                "attempt_root": str(
                    subject.canonical_attempt_root(fixture.case_id)
                ),
                "core_spec_sha256": subject.core_spec_sha256(fixture.spec),
            }
        ] + [
            {
                "case_id": case_id,
                "attempt_root": str(subject.canonical_attempt_root(case_id)),
                "core_spec_sha256": f"{index + 1:x}" * 64,
            }
            for index, case_id in enumerate(dummy_ids)
        ]
        roster_payload = subject.canonical_json(
            {
                "schema_version": subject.ROSTER_LOCK_SCHEMA,
                "status": "FROZEN_READY_FOR_EXECUTION",
                "case_count": 10,
                "cases": roster_rows,
            }
        )
        fixture.root = fixture.publication_pointer.parent / (
            f".{fixture.publication_pointer.stem}.bundle-"
            f"{subject.sha256_bytes(roster_payload)[:16]}"
        )
        fixture.root.mkdir()
        (fixture.root / "cases").mkdir()
        fixture.roster_lock = fixture.root / "roster_lock.json"
        fixture.spec_path = fixture.root / "cases" / f"{fixture.case_id}.json"
        fixture.build_receipt = fixture.root / "build_receipt.json"
        fixture.roster_lock.write_bytes(roster_payload)
        fixture.spec["roster_lock"] = subject.identity(fixture.roster_lock)
        fixture.write_spec()
        roster_identity = dict(fixture.spec["roster_lock"])
        pointer_cases = [
            {
                "case_id": fixture.case_id,
                "spec": subject.identity(fixture.spec_path),
                "core_spec_sha256": subject.core_spec_sha256(fixture.spec),
            }
        ] + [
            {
                "case_id": case_id,
                "spec": {
                    "path": str(
                        (fixture.root / "cases" / f"{case_id}.json").resolve()
                    ),
                    "size_bytes": 0,
                    "sha256": "0" * 64,
                },
                "core_spec_sha256": roster_rows[index + 1][
                    "core_spec_sha256"
                ],
            }
            for index, case_id in enumerate(dummy_ids)
        ]
        claims = {"hfnet_started": False}
        fixture.build_receipt.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "aqua-fe-hfnet-v6-samehistory-roster-build-receipt-v1"
                    ),
                    "status": "FROZEN_READY_FOR_EXECUTION",
                    "roster_lock": roster_identity,
                    "cases": pointer_cases,
                    "claims": claims,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        fixture.publication_pointer.write_text(
            json.dumps(
                {
                    "schema_version": subject.PUBLICATION_POINTER_SCHEMA,
                    "status": "FROZEN_READY_FOR_EXECUTION",
                    "bundle_root": str(fixture.root.resolve()),
                    "roster_lock": roster_identity,
                    "build_receipt": subject.identity(fixture.build_receipt),
                    "cases": pointer_cases,
                    "claims": claims,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(subject, "EXPECTED_ROSTER_SIZE", 10):
            with self.assertRaises(subject.ContractError):
                subject.validate_spec(fixture.spec_path)

    def test_prepared_launch_is_reconstructed_and_tamper_rejected(self) -> None:
        fixture = self.fixture()
        stack, patcher = self.fake_stack()
        with patcher:
            prepared = fixture.materialize_prepared(stack)
            subject.require_prepared_contract(fixture.spec_path, fixture.spec, prepared)
            prepared["launch"]["argv"][0] = "/tmp/not-hfnet"
            subject.attempt_paths(fixture.spec)["prepared"].write_bytes(
                subject.canonical_json(prepared)
            )
            with self.assertRaisesRegex(
                subject.ContractError, "PREPARED_LAUNCH_CONTRACT_MISMATCH"
            ):
                subject.require_prepared_contract(
                    fixture.spec_path, fixture.spec, prepared
                )

    def test_precheck_rejects_broken_terminal_receipt_symlink(self) -> None:
        fixture = self.fixture()
        stack, patcher = self.fake_stack()
        with patcher:
            fixture.materialize_prepared(stack)
            paths = subject.attempt_paths(fixture.spec)
            paths["result"].symlink_to(self.root / "missing-result-target")
            check = subject._check_locked(
                fixture.spec_path,
                require_unclaimed=True,
                resource={"ready": True, "errors": []},
                lock_evidence={"fixture": True},
            )
        self.assertFalse(check["ready"])
        self.assertIn("RUN_RESULT_ALREADY_EXISTS_TERMINAL", check["errors"])

    def test_parse_log_pairs_reset_only_with_subsequent_init(self) -> None:
        path = self.root / "stdout.log"
        path.write_text(
            "Init frame id: 0\n"
            "SYSTEM-> Reseting active map in monocular case\n"
            "mnFirstFrameId = 5\n"
            "135 Frames set to lost\n"
            "Init frame id: 54\n",
            encoding="utf-8",
        )
        value = subject.parse_log(path)
        self.assertEqual(
            value["reset_events"],
            [{"preceding_init_frame_id": 0, "next_init_frame_id": 54}],
        )
        self.assertTrue(value["reset_next_initialization_parse_complete"])

    def test_reset_gate_only_accepts_reset_proven_before_support(self) -> None:
        trajectory = {"longest_contiguous_relative_indices_inclusive": [20, 89]}
        log = {
            "init_frame_ids": [7, 20, 54, 95],
            "reset_events": [
                {"preceding_init_frame_id": 7, "next_init_frame_id": 12},
                {"preceding_init_frame_id": 20, "next_init_frame_id": 54},
                {"preceding_init_frame_id": 54, "next_init_frame_id": None},
            ],
        }
        value = subject.events_in_accepted_support(log, trajectory)
        self.assertEqual(len(value["proven_early_reset_events"]), 1)
        self.assertEqual(len(value["unresolved_reset_events"]), 2)
        self.assertEqual(value["reinitialization_frame_ids"], [54])

    def test_atomic_publication_and_o_excl_reservation_do_not_clobber(self) -> None:
        output = self.root / "atomic/result.json"
        subject._atomic_publish_exclusive(output, b"complete\n")
        self.assertEqual(output.read_bytes(), b"complete\n")
        with self.assertRaisesRegex(
            subject.ContractError, "EXCLUSIVE_PUBLICATION_EXISTS"
        ):
            subject._atomic_publish_exclusive(output, b"replacement\n")
        self.assertEqual(output.read_bytes(), b"complete\n")
        reservation = self.root / "claims/case.start_once"
        subject._write_o_excl_reservation(reservation, b"first\n")
        with self.assertRaises(FileExistsError):
            subject._write_o_excl_reservation(reservation, b"second\n")
        self.assertEqual(reservation.read_bytes(), b"first\n")

    def test_mkdir_and_large_file_publication_are_no_clobber(self) -> None:
        directory = self.root / "reserved"
        subject._mkdir_exclusive(directory)
        with self.assertRaisesRegex(
            subject.ContractError, "EXCLUSIVE_DIRECTORY_PUBLICATION_EXISTS"
        ):
            subject._mkdir_exclusive(directory)
        source = self.root / "source.bin"
        source.write_bytes(b"immutable")
        expected = subject.identity(source)
        target = directory / "target.bin"
        subject._copy_file_atomic_exclusive(source, target, expected)
        self.assertEqual(target.read_bytes(), b"immutable")
        with self.assertRaisesRegex(
            subject.ContractError, "EXCLUSIVE_PUBLICATION_EXISTS"
        ):
            subject._copy_file_atomic_exclusive(source, target, expected)
        self.assertEqual(target.read_bytes(), b"immutable")

    def test_prepare_publishes_manifest_last_on_fuse_safe_path(self) -> None:
        fixture = self.fixture()
        model = self.root / "shared.onnx"
        cache = self.root / "shared.cache"
        model.write_bytes(b"onnx")
        cache.write_bytes(b"cache")
        stack = {"fixture": True}
        expected_stack = {
            "binary": (1, "1" * 64),
            "official_library": (1, "2" * 64),
            "onnx": (model.stat().st_size, subject.sha256_file(model)),
            "cache": (cache.stat().st_size, subject.sha256_file(cache)),
        }
        publications: list[str] = []
        real_publish = subject._atomic_publish_exclusive

        def observe(path: Path, payload: bytes, mode: int = 0o444) -> None:
            publications.append(path.name)
            real_publish(path, payload, mode)

        with mock.patch.multiple(
            subject,
            SHARED_MODEL=model,
            SHARED_CACHE=cache,
            EXPECTED_STACK=expected_stack,
            require_stack=mock.Mock(return_value=stack),
        ), mock.patch.object(
            subject, "_atomic_publish_exclusive", side_effect=observe
        ):
            manifest = subject.prepare(fixture.spec_path)
        paths = subject.attempt_paths(fixture.spec)
        self.assertEqual(manifest["status"], "PREPARED_NOT_STARTED")
        self.assertEqual(publications[-1], paths["prepared"].name)
        self.assertTrue(paths["prepared"].is_file())
        self.assertTrue(paths["result_dir"].is_dir())

    def test_prepare_failure_before_manifest_cleans_owned_attempt(self) -> None:
        fixture = self.fixture()
        stack, patcher = self.fake_stack()
        del stack
        with patcher, mock.patch.object(
            subject,
            "_copy_file_atomic_exclusive",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                subject.prepare(fixture.spec_path)
        self.assertFalse(subject.attempt_paths(fixture.spec)["root"].exists())

    def test_indeterminate_manifest_publication_leaves_blocking_incident(self) -> None:
        fixture = self.fixture()
        model = self.root / "shared.onnx"
        cache = self.root / "shared.cache"
        model.write_bytes(b"onnx")
        cache.write_bytes(b"cache")
        expected_stack = {
            "binary": (1, "1" * 64),
            "official_library": (1, "2" * 64),
            "onnx": (model.stat().st_size, subject.sha256_file(model)),
            "cache": (cache.stat().st_size, subject.sha256_file(cache)),
        }
        real_publish = subject._atomic_publish_exclusive

        def publish_then_report_indeterminate(
            path: Path, payload: bytes, mode: int = 0o444
        ) -> None:
            real_publish(path, payload, mode)
            if path.name == "prepared_manifest.json":
                raise OSError("directory fsync confirmation lost")

        with mock.patch.multiple(
            subject,
            SHARED_MODEL=model,
            SHARED_CACHE=cache,
            EXPECTED_STACK=expected_stack,
            require_stack=mock.Mock(return_value={"fixture": True}),
        ), mock.patch.object(
            subject,
            "_atomic_publish_exclusive",
            side_effect=publish_then_report_indeterminate,
        ):
            with self.assertRaisesRegex(OSError, "fsync confirmation lost"):
                subject.prepare(fixture.spec_path)
        paths = subject.attempt_paths(fixture.spec)
        self.assertTrue(paths["prepared"].is_file())
        self.assertTrue(paths["prepare_incident"].is_file())
        with self.assertRaisesRegex(
            subject.ContractError, "PREPARATION_INCIDENT_PRESENT_NOT_RUNNABLE"
        ):
            subject.load_prepared(fixture.spec_path)

    def test_global_serial_lock_rejects_second_holder(self) -> None:
        with subject.global_serial_lock():
            with self.assertRaisesRegex(
                subject.ContractError, "GLOBAL_SERIAL_LOCK_BUSY"
            ):
                with subject.global_serial_lock():
                    self.fail("second lock unexpectedly acquired")

    @staticmethod
    def command_runner(gpu_line: str, compute_line: str = "") -> object:
        def run(
            argv: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            stdout = compute_line if "--query-compute-apps" in argv[1] else gpu_line
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        return run

    def make_proc(
        self, pid: int, executable: str, comm: str, tokens: list[str]
    ) -> Path:
        proc = self.root / "proc"
        entry = proc / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "exe").symlink_to(executable)
        (entry / "comm").write_text(comm + "\n", encoding="utf-8")
        (entry / "cmdline").write_bytes(
            b"\0".join(item.encode() for item in tokens) + b"\0"
        )
        return proc

    def test_gpu_gate_records_non_4096_gpu_and_finds_python_roscore(self) -> None:
        proc = self.make_proc(
            123,
            "/usr/bin/python3.8",
            "python3.8",
            ["/usr/bin/python3", "/opt/ros/noetic/bin/roscore"],
        )
        gate = subject.resource_gate(
            proc_root=proc,
            command_runner=self.command_runner(
                "Cloud GPU, GPU-1, 550.1, 24576, 1024, 23552\n"
            ),
        )
        self.assertIn("CONFLICTING_SLAM_OR_ROS_PROCESS_PRESENT", gate["errors"])
        self.assertEqual(gate["memory_total_mib"], 24576)
        self.assertTrue(gate["gpu_hardware_not_method_gated"])

    def test_todesk_waiver_is_exact_not_argument_substring(self) -> None:
        proc = self.make_proc(
            124, "/usr/bin/python3", "python3", ["python3", "ToDesk"]
        )
        gate = subject.resource_gate(
            proc_root=proc,
            command_runner=self.command_runner(
                "GPU, GPU-1, 550.1, 8192, 100, 8092\n",
                "124, python3, 100\n",
            ),
        )
        self.assertIn("COMPETING_GPU_COMPUTE_APPLICATION_PRESENT", gate["errors"])

    def test_execute_once_popen_failure_is_terminal_data(self) -> None:
        paths = {
            "stdout": self.root / "stdout.log",
            "stderr": self.root / "stderr.log",
        }
        spec = {"timeout_seconds": 60}
        launch = {"argv": ["false"], "cwd": str(self.root)}
        with mock.patch.object(subject.subprocess, "Popen", side_effect=OSError("boom")):
            execution = subject.execute_once(spec, paths, launch)
        self.assertEqual(execution["popen_invocations"], 1)
        self.assertFalse(execution["child_reaped_before_post_audit"])
        self.assertIn("POPEN_FAILED:OSError:boom", execution["supervisor_error"])

    def test_run_writes_terminal_fail_and_permanent_claim_without_retry(self) -> None:
        fixture = self.fixture()
        stack, patcher = self.fake_stack()
        ready = {"ready": True, "errors": [], "memory_total_mib": 8192}
        with patcher:
            fixture.materialize_prepared(stack)
            with mock.patch.object(
                subject, "resource_gate", return_value=ready
            ), mock.patch.object(
                subject.subprocess, "Popen", side_effect=OSError("no process")
            ):
                result = subject.run(
                    fixture.spec_path, fixture.spec["authorization_token"]
                )
            self.assertEqual(
                result["status"], "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"
            )
            paths = subject.attempt_paths(fixture.spec)
            self.assertTrue(paths["result"].is_file())
            self.assertTrue(
                subject.permanent_case_paths(fixture.case_id)["reservation"].is_file()
            )
            with mock.patch.object(subject, "resource_gate", return_value=ready):
                with self.assertRaisesRegex(
                    subject.ContractError, "PRESTART_CHECK_FAILED.*CLAIMED_NO_RETRY"
                ):
                    subject.run(
                        fixture.spec_path, fixture.spec["authorization_token"]
                    )

    def test_reservation_sync_failure_after_o_excl_gets_terminal_receipt(self) -> None:
        fixture = self.fixture()
        stack, patcher = self.fake_stack()
        ready = {"ready": True, "errors": [], "memory_total_mib": 8192}

        def claimed_then_fail(path: Path, payload: bytes) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            raise subject.ClaimedBoundaryError("directory fsync failed")

        with patcher:
            fixture.materialize_prepared(stack)
            with mock.patch.object(
                subject, "resource_gate", return_value=ready
            ), mock.patch.object(
                subject,
                "_write_o_excl_reservation",
                side_effect=claimed_then_fail,
            ), mock.patch.object(subject.subprocess, "Popen") as popen:
                result = subject.run(
                    fixture.spec_path, fixture.spec["authorization_token"]
                )
        self.assertEqual(
            result["status"], "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"
        )
        self.assertTrue(subject.attempt_paths(fixture.spec)["result"].is_file())
        popen.assert_not_called()

    def test_run_fail_cli_exit_is_two(self) -> None:
        with mock.patch.object(
            subject,
            "run",
            return_value={"status": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"},
        ), redirect_stdout(io.StringIO()):
            code = subject.main(
                [
                    "run",
                    "--case-spec",
                    str(self.root / "unused.json"),
                    "--authorization-token",
                    "unused",
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
