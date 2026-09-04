from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_p07_backend_execution_lock_v1 as lock_builder
from scripts import build_p07_backend_replacement_contract_v1 as replacement
from scripts import build_p07_backend_replay_queue_v1 as queue_builder
from scripts import p07_backend_replay_common_v1 as runtime_common
from scripts import register_p07_backend_allocations_v1 as registration
from scripts.tests.test_p07_backend_replay_queue_v1 import HASHES, fixture_snapshot


def record(path: str, token: str) -> dict[str, object]:
    return {"path": path, "sha256": token, "size_bytes": 123}


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def data_identity_snapshot(rows: list[dict[str, str]]) -> dict[str, object]:
    bindings: list[dict[str, object]] = []
    entries: list[dict[str, object]] = []
    for family, sequence in sorted(
        {(row["dataset_family"], row["sequence"]) for row in rows}
    ):
        raw = f"datasets/{family}/{sequence}.bag"
        reference = f"datasets/{family}/{sequence}.tum"
        bindings.append(
            {
                "dataset_family": family,
                "sequence": sequence,
                "raw_input_path": raw,
                "reference_path": reference,
                "calibration_paths": [],
            }
        )
        for path, kind in ((raw, "raw"), (reference, "reference")):
            entries.append(
                {
                    "path": path,
                    "path_kind": "PLAIN_REGULAR_FILE",
                    "symlink_components": [],
                    "resolved_target_path": f"/fixture/{path}",
                    "resolved_target_identity": {
                        "device": 1,
                        "inode": len(entries) + 1,
                        "mode": 0o100644,
                        "size_bytes": 123,
                        "mtime_ns": 1,
                        "owner_uid": 1000,
                    },
                    "expected_sha256": digest(path),
                    "kinds": [kind],
                    "datasets": [f"{family}:{sequence}"],
                    "sha256_verified_at_freeze": True,
                }
            )
    payload: dict[str, object] = {
        "schema_version": runtime_common.DATA_IDENTITY_SCHEMA,
        "status": runtime_common.DATA_IDENTITY_STATUS,
        "manifest_records": [
            record(
                "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
                digest("eligibility"),
            ),
            record(
                "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
                digest("checksums"),
            ),
            record(
                "papers/ieee_sensors_journal_experiments/reference_audit.csv",
                digest("reference-audit"),
            ),
        ],
        "dataset_bindings": bindings,
        "entries": entries,
        "verification": {
            "full_sha256_once_at_execution_lock_freeze": True,
            "stat_identity_before_each_replay": True,
            "manifest_files_rehashed_before_each_replay": True,
            "symlink_chain_before_each_replay": True,
            "trajectory_values_interpreted": False,
        },
    }
    payload[runtime_common.DATA_IDENTITY_SELF_HASH] = (
        runtime_common.canonical_json_hash(
            payload, runtime_common.DATA_IDENTITY_SELF_HASH
        )
    )
    return payload


def b0_play_inputs(rows: list[dict[str, str]]) -> dict[str, object]:
    b0_rows = [row for row in rows if row["arm"] == runtime_common.B0_ARM]
    entries: list[dict[str, object]] = []
    ids: dict[str, str] = {}
    for row in b0_rows:
        if row["window_id"] in ids:
            continue
        play_id = digest(f"play:{row['window_id']}")
        ids[row["window_id"]] = play_id
        entries.append(
            {
                "play_input_id": play_id,
                "window_id": row["window_id"],
                "dataset_family": row["dataset_family"],
                "sequence": row["sequence"],
                "runner_start": row["runner_start"],
                "runner_end_or_duration": row["runner_end_or_duration"],
                "runner_unit": row["runner_unit"],
                "expected_sha256": digest(f"bag:{row['window_id']}"),
                "source_provenance_hash": row["source_provenance_hash"],
                "path_identity": {
                    "path": f"datasets/b0/{play_id}.bag",
                    "path_kind": "PLAIN_REGULAR_FILE",
                    "symlink_components": [],
                    "resolved_target_path": f"/fixture/b0/{play_id}.bag",
                    "resolved_target_identity": {
                        "device": 1,
                        "inode": len(entries) + 100,
                        "mode": 0o100644,
                        "size_bytes": 123,
                        "mtime_ns": 1,
                        "owner_uid": 1000,
                    },
                    "expected_sha256": digest(f"bag:{row['window_id']}"),
                },
                "derivation": {
                    "kind": "DIRECT_RAW_WINDOW_PLAYBACK",
                    "source_raw_path": f"datasets/raw/{row['sequence']}.bag",
                    "source_raw_sha256": digest(f"raw:{row['sequence']}"),
                    "derivation_hash": digest(f"derivation:{row['window_id']}"),
                },
                "evaluation_window": {
                    "start_ros_time_ns": 1_700_000_000_000_000_000 + len(entries),
                    "end_ros_time_ns": 1_700_000_001_000_000_000 + len(entries),
                    "camera_topic": "/camera/image_raw",
                    "stamp_source": "sensor_msgs/Image.header.stamp",
                    "boundary_rule": (
                        "FIRST_INCLUDED_CAMERA_STAMP_TO_LAST_INCLUDED_CAMERA_STAMP_INCLUSIVE"
                    ),
                    "derivation_evidence": record(
                        "papers/ieee_sensors_journal_experiments/p07/"
                        "backend_b0_materialization_receipt_v1.json",
                        digest("b0-receipt"),
                    ),
                },
            }
        )
    bindings = [
        {
            "queue_index": int(row["queue_index"]),
            "run_id": row["run_id"],
            "play_input_id": ids[row["window_id"]],
            "window_id": row["window_id"],
            "dataset_family": row["dataset_family"],
            "sequence": row["sequence"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"],
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
        }
        for row in b0_rows
    ]
    payload: dict[str, object] = {
        "schema_version": runtime_common.B0_PLAY_INPUTS_SCHEMA,
        "status": runtime_common.B0_PLAY_INPUTS_STATUS,
        "materialization_lock_hash": digest("b0-plan-self"),
        "materialization_intent_hash": digest("b0-intent-self"),
        "materialization_receipt_hash": digest("b0-receipt-self"),
        "materialization_receipt": record(
            runtime_common.B0_MATERIALIZATION_RECEIPT_PATH,
            digest("b0-receipt"),
        ),
        "entries": entries,
        "queue_bindings": bindings,
        "policy": {
            "all_b0_queue_rows_bound": True,
            "full_sha256_before_and_after_each_replay": True,
            "path_link_target_identity_before_and_after_each_replay": True,
            "preparation_must_not_create_or_replace_play_input": True,
            "derived_inputs_materialized_before_execution_lock": True,
            "trajectory_values_interpreted": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": runtime_common.B0_OUTCOME_BOUNDARY,
    }
    payload[runtime_common.B0_PLAY_INPUTS_SELF_HASH] = (
        runtime_common.canonical_json_hash(
            payload, runtime_common.B0_PLAY_INPUTS_SELF_HASH
        )
    )
    return payload


class P07BackendExecutionLockV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = queue_builder.build_queue_rows(
            fixture_snapshot(applicable_windows=1),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        self.g0_lock_record = record(
            "papers/ieee_sensors_journal_experiments/p07/g0_evaluation_lock_v1.json",
            digest("g0-lock"),
        )
        self.g0_authority = {
            "schema_version": lock_builder.g0_governance.EXECUTION_AUTHORITY_SCHEMA,
            "status": lock_builder.g0_governance.EXECUTION_AUTHORITY_STATUS,
            "evaluation_lock": {
                **self.g0_lock_record,
                "evaluation_lock_hash": digest("g0-lock-self"),
            },
            "g0_execution_authority_hash": digest("g0-authority"),
        }
        self.g0_patch = mock.patch.object(
            lock_builder.g0_governance,
            "validate_execution_authority_binding",
            return_value=self.g0_authority["g0_execution_authority_hash"],
        )
        self.g0_patch.start()
        runtime_records = {}
        for role, relative in (
            runtime_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.items()
        ):
            path = queue_builder.ROOT / relative
            runtime_records[role] = {
                "path": relative,
                "sha256": runtime_common.sha256(path),
                "size_bytes": path.stat().st_size,
            }
        frozen_artifacts = [
            *runtime_records.values(),
            record(queue_builder.display_path(lock_builder.B0_PLAN), digest("b0-plan")),
            record(
                queue_builder.display_path(lock_builder.B0_INTENT),
                digest("b0-intent"),
            ),
            record(
                queue_builder.display_path(lock_builder.B0_RECEIPT),
                digest("b0-receipt"),
            ),
            record(
                queue_builder.display_path(lock_builder.B0_PLAY_INPUTS),
                digest("b0-play-inputs"),
            ),
            self.g0_lock_record,
        ]
        self.common = {
            "frozen_at": "2026-08-08T00:01:00+08:00",
            "queue_rows": self.rows,
            "queue_record": record("queue.csv", HASHES[0]),
            "allocation_record": record("allocation.csv", HASHES[1]),
            "queue_lock_record": {
                **record("queue-lock.json", HASHES[2]),
                "backend_queue_lock_hash": HASHES[3],
            },
            "validation_record": record("validation.json", HASHES[4]),
            "registration_record": record("registration.json", HASHES[3]),
            "allowed_entrypoint_record": runtime_records["job_entrypoint"],
            "executor_record": runtime_records["job_entrypoint"],
            "adapter_record": runtime_records["adapter"],
            "auditor_record": runtime_records["auditor"],
            "artifacts": frozen_artifacts,
            "external_runtime_bindings": {
                role: lock_builder._external_record(  # noqa: SLF001
                    path, label=f"fixture VINS runtime {role}"
                )
                for role, path in runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS.items()
            },
            "replacement_contract_binding": {
                "schema_version": replacement.SCHEMA,
                "status": replacement.STATUS,
                "contract": record(
                    "papers/ieee_sensors_journal_experiments/p07/"
                    "backend_replacement_contract_v1.json",
                    HASHES[4],
                ),
                "replacement_contract_hash": HASHES[7],
            },
            "data_identity_snapshot": data_identity_snapshot(self.rows),
            "b0_play_inputs": b0_play_inputs(self.rows),
            "g0_pre_replay_authority": self.g0_authority,
            "mutable_registry_prefix": {
                "path": "run_registry.csv",
                "sha256": HASHES[6],
                "size_bytes": 456,
            },
            "output_free_bytes": 10**12,
            "governance_free_bytes": 10**12,
        }

    def tearDown(self) -> None:
        self.g0_patch.stop()

    def test_lock_binds_serial_order_capacity_and_no_clobber_policy(self) -> None:
        payload = lock_builder.build_lock_payload(**self.common)
        self.assertEqual(payload["schema_version"], lock_builder.SCHEMA)
        self.assertEqual(payload["status"], lock_builder.STATUS)
        self.assertEqual(payload["queue_items"], 243)
        self.assertEqual(payload["global_flock_path"], lock_builder.GLOBAL_FLOCK_PATH)
        self.assertEqual(
            payload["execution_lock_hash"], lock_builder.execution_lock_hash(payload)
        )
        self.assertTrue(payload["serialization"]["one_ros_vins_rosbag_group_at_a_time"])
        self.assertTrue(payload["adapter_policy"]["input_sha256_before_and_after_required"])
        self.assertTrue(payload["adapter_policy"]["target_no_clobber"])
        self.assertTrue(payload["adapter_policy"]["job_is_only_entrypoint"])
        self.assertTrue(payload["adapter_policy"]["adapter_direct_cli_forbidden"])
        self.assertTrue(
            payload["adapter_policy"]["feature_arms_require_sealed_memfd_copy"]
        )
        self.assertTrue(
            payload["adapter_policy"]["preparation_runners_run_vins_zero_only"]
        )
        self.assertTrue(
            payload["adapter_policy"]["replay_only_runner_is_only_ros_replay_path"]
        )
        self.assertTrue(
            payload["adapter_policy"]["evaluation_during_replay_forbidden"]
        )
        self.assertEqual(
            payload["adapter_policy"]["required_environment"]["preparation"],
            {
                "RUN_VINS": "0",
                "FORCE_EXPORT": "0",
                "EXPORT_FEATURES": "0",
                "RUN_EVALUATION": "0",
            },
        )
        self.assertTrue(payload["data_identity_policy"]["check_before_each_replay"])
        self.assertFalse(
            payload["data_identity_policy"][
                "trajectory_values_read_by_identity_check"
            ]
        )
        self.assertEqual(
            payload["infrastructure_replacement"]["replacement_contract_hash"],
            HASHES[7],
        )
        self.assertEqual(
            payload["infrastructure_replacement"][
                "allowed_effective_row_overrides"
            ],
            ["run_id", "runner_tag", "expected_run_dir", "expected_attempt_dir"],
        )
        self.assertEqual(payload["capacity_gate"]["margin_numerator"], 6)
        self.assertEqual(payload["capacity_gate"]["margin_denominator"], 5)
        self.assertEqual(payload["capacity_gate"]["reserve_bytes"], 2 * 1024**3)
        self.assertEqual(payload["capacity_gate"]["insufficient_action"], "WAITING")
        self.assertFalse(payload["trajectory_outcome_read_at_freeze"])
        self.assertEqual(payload["b0_play_inputs"], self.common["b0_play_inputs"])
        self.assertEqual(
            payload[lock_builder.g0_governance.EXECUTION_LOCK_BINDING_KEY],
            self.g0_authority,
        )
        self.assertEqual(
            payload["execution_order"][0]["source_provenance_hash"],
            self.rows[0]["source_provenance_hash"],
        )

    def test_capacity_failure_never_produces_ready_lock(self) -> None:
        arguments = dict(self.common)
        arguments["output_free_bytes"] = 0
        with self.assertRaisesRegex(lock_builder.ExecutionLockError, "output capacity"):
            lock_builder.build_lock_payload(**arguments)
        arguments = dict(self.common)
        arguments["governance_free_bytes"] = 0
        with self.assertRaisesRegex(lock_builder.ExecutionLockError, "governance capacity"):
            lock_builder.build_lock_payload(**arguments)

    def test_formal_artifact_set_includes_direct_runners_and_contracts(self) -> None:
        names = {path.name for path in lock_builder.required_artifact_paths()}
        self.assertTrue(
            {
                "run_aqualoc_archaeo_vins_eval.sh",
                "run_aqualoc_real_vins_eval.sh",
                "run_ntnu_vins_eval.sh",
                "run_afrl_cave_vins_eval.sh",
                "run_isj_b0_native_vins_guarded_v1.sh",
                "backend_quality_contract_v1.json",
                "backend_consumer_contract_xfeat_v1.json",
                "run_p07_backend_replay_adapter_v1.py",
                "run_p07_backend_replay_job_v1.py",
                "audit_p07_backend_replay_v1.py",
                "run_p07_backend_replay_only_v1.sh",
                "prepare_p07_backend_replay_config_v1.py",
                "check_b0_vins_origin_identity_v1.py",
                "check_nativeq_backend_contract.py",
                "build_nativeq_backend_contract.py",
                "check_p05_xfeat_backend_contract_v1.py",
                "p07_backend_sealed_runtime_v1.py",
                "data_eligibility_manifest.csv",
                "dataset_checksum_manifest.txt",
                "reference_audit.csv",
                "backend_replacement_contract_v1.json",
                "build_p07_backend_replacement_contract_v1.py",
                "allocate_p07_backend_replacement_v1.py",
                "run_p07_backend_serial_queue_v1.py",
                "test_p07_backend_runtime_identity_v1.py",
                "backend_b0_materialization_lock_v1.json",
                "backend_b0_materialization_intent_v1.json",
                "backend_b0_materialization_receipt_v1.json",
                "backend_b0_play_inputs_v1.json",
                "build_p07_backend_b0_materialization_lock_v1.py",
                "run_p07_backend_b0_materialization_v1.py",
                "test_p07_backend_b0_materialization_v1.py",
                "g0_evaluation_lock_v1.json",
                "p07_g0_governance_v1.py",
            }.issubset(names)
        )

    def test_lock_binds_exact_vins_binary_and_project_libraries(self) -> None:
        payload = lock_builder.build_lock_payload(**self.common)
        self.assertEqual(
            set(payload["external_runtime_bindings"]),
            set(runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS),
        )
        for role, path in runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS.items():
            record = payload["external_runtime_bindings"][role]
            self.assertEqual(record["path"], str(path))
            self.assertEqual(record["sha256"], runtime_common.sha256(path))
            self.assertEqual(record["size_bytes"], path.stat().st_size)
        self.assertTrue(
            payload["adapter_policy"][
                "controller_job_and_transitive_modules_require_sealed_memfd"
            ]
        )
        self.assertTrue(
            payload["adapter_policy"][
                "vins_pid_exe_and_maps_identity_check_required"
            ]
        )

    def test_missing_replacement_contract_never_produces_ready_lock(self) -> None:
        arguments = dict(self.common)
        arguments["replacement_contract_binding"] = {}
        with self.assertRaisesRegex(lock_builder.ExecutionLockError, "replacement"):
            lock_builder.build_lock_payload(**arguments)

    def test_data_identity_freezes_canonical_symlink_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mounted = root / "mounted"
            mounted.mkdir()
            raw = mounted / "fjord.bag"
            reference = mounted / "fjord.tum"
            raw.write_bytes(b"raw")
            reference.write_bytes(b"reference")
            (root / "datasets").symlink_to(mounted, target_is_directory=True)
            manifests = root / "papers/ieee_sensors_journal_experiments"
            manifests.mkdir(parents=True)
            eligibility = manifests / "data_eligibility_manifest.csv"
            eligibility.write_text(
                "dataset_family,sequence,eligibility,raw_input_path,reference_path,"
                "calibration_paths,expected_raw_size_bytes,raw_size_bytes\n"
                "ntnu,fjord_6,ELIGIBLE,datasets/fjord.bag,datasets/fjord.tum,,3,3\n",
                encoding="utf-8",
            )
            reference_audit = manifests / "reference_audit.csv"
            reference_audit.write_text(
                "dataset_family,sequence,raw_input_path,reference_path,reference_exists,"
                "eligibility,reference_sha256\n"
                "ntnu,fjord_6,datasets/fjord.bag,datasets/fjord.tum,true,ELIGIBLE,"
                f"{runtime_common.sha256(reference)}\n",
                encoding="utf-8",
            )
            checksums = manifests / "dataset_checksum_manifest.txt"
            checksums.write_text(
                f"{runtime_common.sha256(raw)}  datasets/fjord.bag\n"
                f"{runtime_common.sha256(reference)}  datasets/fjord.tum\n",
                encoding="utf-8",
            )
            snapshot = lock_builder.collect_data_identity_snapshot(
                [{"dataset_family": "ntnu", "sequence": "fjord_6"}],
                root=root,
                eligibility_path=eligibility,
                checksum_path=checksums,
                reference_audit_path=reference_audit,
            )
            runtime_common.validate_data_identity_snapshot_shape(
                snapshot, [{"dataset_family": "ntnu", "sequence": "fjord_6"}]
            )
            self.assertTrue(
                all(entry["symlink_components"] for entry in snapshot["entries"])
            )

    def test_formal_writer_delegates_to_no_clobber_publisher(self) -> None:
        with mock.patch.object(
            queue_builder.formal_io, "global_formal_lock"
        ), mock.patch.object(
            queue_builder.formal_io, "publish_bytes_no_clobber"
        ) as publisher:
            payload = {"fixture": True}
            lock_builder.write_no_clobber(lock_builder.OUTPUT, payload)
        publisher.assert_called_once()
        args, kwargs = publisher.call_args
        self.assertEqual(args[:2], (
            queue_builder.ROOT,
            queue_builder.display_path(lock_builder.OUTPUT),
        ))
        self.assertEqual(args[2], queue_builder.formal_io.json_bytes(payload))
        self.assertTrue(callable(kwargs["pre_link_guard"]))
        self.assertTrue(callable(kwargs["post_link_guard"]))

    def test_publication_guard_rejects_rehashed_artifact_drift(self) -> None:
        payload = lock_builder.build_lock_payload(**self.common)
        registry = b"frozen registry prefix\n"
        payload["mutable_registry_prefix"] = {
            "path": queue_builder.display_path(registration.RUN_REGISTRY),
            "sha256": hashlib.sha256(registry).hexdigest(),
            "size_bytes": len(registry),
        }
        payload["execution_lock_hash"] = lock_builder.execution_lock_hash(payload)
        records = {
            str(item["path"]): dict(item) for item in payload["artifacts"]
        }

        def observed(path: Path) -> dict[str, object]:
            return records[queue_builder.display_path(path)]

        with mock.patch.object(
            lock_builder, "_record_dict", side_effect=observed
        ), mock.patch.object(
            lock_builder, "_read_direct_bytes", return_value=registry
        ):
            lock_builder._revalidate_execution_publication_inputs(payload)

        first = next(iter(records))
        drifted = {key: dict(value) for key, value in records.items()}
        drifted[first]["sha256"] = "f" * 64

        def observed_drift(path: Path) -> dict[str, object]:
            return drifted[queue_builder.display_path(path)]

        with mock.patch.object(
            lock_builder, "_record_dict", side_effect=observed_drift
        ), mock.patch.object(
            lock_builder, "_read_direct_bytes", return_value=registry
        ), self.assertRaisesRegex(lock_builder.ExecutionLockError, "artifact drift"):
            lock_builder._revalidate_execution_publication_inputs(payload)

    def test_portable_record_match_accepts_direct_reader_inode_metadata(self) -> None:
        expected = record("papers/p07/frozen.json", HASHES[0])
        observed = {**expected, "device": 11, "inode": 29}
        self.assertTrue(
            lock_builder._same_portable_file_record(observed, expected)
        )
        self.assertFalse(
            lock_builder._same_portable_file_record(
                {**observed, "sha256": HASHES[1]}, expected
            )
        )

    def test_required_artifact_record_rejects_broken_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact.json"
            artifact.symlink_to("missing.json")
            with mock.patch.object(queue_builder, "ROOT", root):
                with self.assertRaisesRegex(
                    lock_builder.ExecutionLockError, "read direct"
                ):
                    lock_builder._record_dict(artifact)


if __name__ == "__main__":
    unittest.main()
