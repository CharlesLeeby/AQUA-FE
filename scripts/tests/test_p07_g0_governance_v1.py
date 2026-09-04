from __future__ import annotations

import copy
from contextlib import ExitStack
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import build_p07_backend_replay_queue_v1 as queue_builder
from scripts import build_p07_backend_formalization_adoption_v1 as adoption
from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_builder
from scripts import build_p07_g0_evaluation_lock_v1 as g0_lock_builder
from scripts import build_p07_g0_reference_contracts_v1 as references
from scripts import collect_p07_backend_failure_v1 as collector
from scripts import materialize_p07_g0_jobs_v1 as materializer
from scripts import p07_backend_evaluation_v1 as evaluation
from scripts import p07_backend_formal_io_v1 as formal_io
from scripts import p07_backend_replay_common_v1 as backend_runtime
from scripts import p07_g0_governance_v1 as gov
from scripts import p07_g0_publisher_v1 as publisher
from scripts import reduce_p07_g0_results_v1 as reducer
from scripts import run_p07_g0_evaluation_v1 as runner
from scripts import evaluate_vins_common_support_epoch_v2 as common_support_evaluator
from scripts.tests.test_p07_backend_replay_queue_v1 import (
    HASHES,
    fixture_snapshot,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def clean_evidence(
    *, run_id: str, window_id: str, arm: str, replay_index: int
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "window_id": window_id,
        "arm": arm,
        "replay_index": replay_index,
        "algorithmic_slot": True,
        "infrastructure_codes": [],
        "process": {"exit_code": 0, "timed_out": False},
        "trajectory": {
            "present": True,
            "row_count": 4,
            "finite": True,
            "strictly_increasing": True,
        },
        "initialization": {"success": True, "first_output_delay_s": 0.0},
        "support": {"coverage_ratio": 1.0},
        "solver_log_inspected": True,
        "solver_log_text": "",
        "queue": {
            "evidence_status": "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
            "drop_rate": None,
            "backlog_growth_s": None,
        },
    }


class P07EpochAndFailureCollectorTests(unittest.TestCase):
    def test_g0_lock_publication_is_transactional_and_collision_closed(self) -> None:
        for mutation_call in (2, 3):
            with self.subTest(mutation_call=mutation_call), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                paths = {
                    name: root / f"inputs/{name}"
                    for name in (
                        "queue.csv",
                        "audit.csv",
                        "artifact.dat",
                        "registry.csv",
                        "code.py",
                        "adoption.json",
                        "evidence.json",
                    )
                }
                for name, path in paths.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((name + "\n").encode())

                def direct(path: Path) -> dict[str, object]:
                    return publisher.direct_file_record_rooted(
                        root, path, label=f"synthetic transaction {path.name}"
                    )

                reference_path = root / "inputs/reference_contracts.json"
                write_json(
                    reference_path,
                    {
                        "source_backend_queue": direct(paths["queue.csv"]),
                        "reference_audit": direct(paths["audit.csv"]),
                        "contracts": [
                            {"reference_artifact": direct(paths["artifact.dat"])}
                        ],
                    },
                )
                payload: dict[str, object] = {
                    "frozen_at": "2026-08-08T00:00:00+08:00",
                    "frozen_inputs": [
                        {
                            **direct(reference_path),
                            "role": "reference_contracts",
                        }
                    ],
                    "code_bindings": [direct(paths["code.py"])],
                    "mutable_registry_prefix": direct(paths["registry.csv"]),
                    "formalization_adoption": direct(paths["adoption.json"]),
                    "formalization_review_evidence": direct(
                        paths["evidence.json"]
                    ),
                }
                output = root / "papers/p07/g0_evaluation_lock.json"
                output.parent.mkdir(parents=True)
                calls = 0

                def rebuild(**_kwargs: object) -> dict[str, object]:
                    nonlocal calls
                    calls += 1
                    if calls == mutation_call:
                        paths["artifact.dat"].write_bytes(b"drift\n")
                    return payload

                with mock.patch.object(
                    g0_lock_builder, "build_lock_payload", side_effect=rebuild
                ):
                    with self.assertRaises(gov.G0GovernanceError):
                        g0_lock_builder.publish_lock_transactional(
                            root=root,
                            output=output,
                            payload=payload,
                            queue_path=paths["queue.csv"],
                            allocation_path=paths["queue.csv"],
                            queue_lock_path=reference_path,
                            precision_lock_path=reference_path,
                            epoch_ns_lock_path=reference_path,
                            reference_contracts_path=reference_path,
                            registry_path=paths["registry.csv"],
                        )
                self.assertFalse(output.exists())
                self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "inputs/source.json"
            output = root / "papers/p07/g0_evaluation_lock.json"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            queue = root / "inputs/queue.csv"
            audit = root / "inputs/audit.csv"
            artifact = root / "inputs/artifact.dat"
            for path in (queue, audit, artifact):
                path.write_bytes(b"fixture\n")
            write_json(
                source,
                {
                    "source_backend_queue": publisher.direct_file_record_rooted(
                        root, queue, label="collision queue"
                    ),
                    "reference_audit": publisher.direct_file_record_rooted(
                        root, audit, label="collision audit"
                    ),
                    "contracts": [
                        {
                            "reference_artifact": publisher.direct_file_record_rooted(
                                root, artifact, label="collision artifact"
                            )
                        }
                    ],
                },
            )
            reference_record = publisher.direct_file_record_rooted(
                root, source, label="collision references"
            )
            payload = {
                "frozen_at": "2026-08-08T00:00:00+08:00",
                "frozen_inputs": [
                    {**reference_record, "role": "reference_contracts"}
                ],
                "code_bindings": [reference_record],
                "mutable_registry_prefix": reference_record,
                "formalization_adoption": reference_record,
                "formalization_review_evidence": reference_record,
            }
            output.write_bytes(b"independent winner\n")
            with self.assertRaises(FileExistsError):
                g0_lock_builder.publish_lock_transactional(
                    root=root,
                    output=output,
                    payload=payload,
                    queue_path=queue,
                    allocation_path=queue,
                    queue_lock_path=source,
                    precision_lock_path=source,
                    epoch_ns_lock_path=source,
                    reference_contracts_path=source,
                    registry_path=queue,
                )
            self.assertEqual(output.read_bytes(), b"independent winner\n")

    def test_g0_formal_json_loaders_reject_duplicate_and_noncanonical_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            relative = Path("papers/ieee_sensors_journal_experiments/p07/lock.json")
            path = root / relative
            path.parent.mkdir(parents=True)
            payload: dict[str, object] = {
                "schema_version": "synthetic-g0-authority-v1",
                "status": "FROZEN_PRE_OUTCOME",
            }
            payload["lock_hash"] = gov.canonical_json_hash(payload)
            publisher.write_json_exclusive_rooted(root, path, payload)
            self.assertEqual(
                gov._read_direct_json(root, path, label="synthetic G0 lock"),
                payload,
            )
            built, _record = g0_lock_builder._direct_json_snapshot(
                root, path, label="synthetic G0 lock"
            )
            self.assertEqual(built, payload)

            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(gov.G0GovernanceError, "canonical"):
                gov._read_direct_json(root, path, label="synthetic G0 lock")
            with self.assertRaisesRegex(gov.G0GovernanceError, "canonical"):
                g0_lock_builder._direct_json_snapshot(
                    root, path, label="synthetic G0 lock"
                )

            canonical = (
                json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
                + "\n"
            )
            duplicate = (
                canonical[:-2]
                + ',\n  "status": "FROZEN_PRE_OUTCOME"\n}\n'
            )
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(gov.G0GovernanceError, "duplicate"):
                gov._read_direct_json(root, path, label="synthetic G0 lock")
            with self.assertRaisesRegex(gov.G0GovernanceError, "duplicate"):
                g0_lock_builder._direct_json_snapshot(
                    root, path, label="synthetic G0 lock"
                )

    def test_required_g0_callers_do_not_use_legacy_path_follow_io(self) -> None:
        legacy_calls = (
            "gov.sha256_file(",
            "gov.file_record(",
            "gov.validate_file_record(",
            "gov.read_json_object(",
            "gov.read_csv(",
            "gov.write_json_exclusive(",
            "gov.validate_output_manifest(",
        )
        path_follow_calls = (
            ".read_text(",
            ".read_bytes(",
            ".write_text(",
            ".write_bytes(",
            ".open(",
            ".exists(",
            ".is_file(",
            ".mkdir(",
            ".rename(",
        )
        offenders: dict[str, list[str]] = {}
        for role, relative in gov.REQUIRED_CODE_BINDING_PATHS.items():
            if role in {"g0_shared_governance", "no_clobber_crash_reconcile_publisher"}:
                continue
            text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            found = [token for token in (*legacy_calls, *path_follow_calls) if token in text]
            if found:
                offenders[relative] = found
        self.assertEqual(offenders, {})

    def test_runner_sealed_input_detects_midrun_source_mutation_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "inputs/trajectory.csv"
            source.parent.mkdir(parents=True)
            source.write_text("1542883756.0,0,0,0\n", encoding="utf-8")
            record = publisher.direct_file_record_bound_input_rooted(
                root, source, label="synthetic runner input"
            )
            publication_marker = root / "receipt-written"
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "source drifted|differs after evaluator"
            ):
                with runner.sealed_bound_input(
                    root, record, label="synthetic runner input"
                ) as (proc_path, descriptor):
                    self.assertEqual(
                        Path(proc_path).read_bytes(), b"1542883756.0,0,0,0\n"
                    )
                    seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
                    self.assertEqual(
                        seals,
                        fcntl.F_SEAL_SHRINK
                        | fcntl.F_SEAL_GROW
                        | fcntl.F_SEAL_WRITE
                        | fcntl.F_SEAL_SEAL,
                    )
                    source.write_text(
                        "1542883756.0,9,9,9\n", encoding="utf-8"
                    )
                publication_marker.write_text("forbidden\n", encoding="utf-8")
            self.assertFalse(publication_marker.exists())

    def test_runner_sealed_code_entrypoint_detects_mutation_and_uses_procfd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            entrypoint = root / "scripts/evaluator.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("print('frozen')\n", encoding="utf-8")
            record = publisher.direct_file_record_bound_input_rooted(
                root, entrypoint, label="synthetic evaluator entrypoint"
            )
            receipt = root / "result_receipt_v1.json"
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "source drifted|differs after evaluator"
            ):
                with runner.sealed_bound_input(
                    root, record, label="synthetic evaluator entrypoint"
                ) as (proc_path, descriptor):
                    self.assertEqual(proc_path, f"/proc/self/fd/{descriptor}")
                    self.assertEqual(Path(proc_path).read_text(encoding="utf-8"), "print('frozen')\n")
                    entrypoint.write_text("print('mutated')\n", encoding="utf-8")
                receipt.write_text("forbidden\n", encoding="utf-8")
            self.assertFalse(receipt.exists())

    def test_collector_reconcile_rejects_leaf_ancestor_and_hardlink_aliases(self) -> None:
        payload = {"schema_version": "synthetic", "value": 1}
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workspace"
            outside = Path(raw) / "outside"
            (root / "direct").mkdir(parents=True)
            outside.mkdir()

            external = outside / "external.json"
            external.write_text(encoded, encoding="utf-8")
            leaf = root / "direct/leaf.json"
            leaf.symlink_to(external)
            with self.assertRaises(gov.G0GovernanceError):
                collector._publish_or_reconcile_exact(
                    root, leaf, payload, label="synthetic leaf"
                )
            self.assertEqual(external.read_text(encoding="utf-8"), encoded)

            leaf.unlink()
            os.link(external, leaf)
            with self.assertRaises(gov.G0GovernanceError):
                collector._publish_or_reconcile_exact(
                    root, leaf, payload, label="synthetic hardlink"
                )
            self.assertEqual(external.read_text(encoding="utf-8"), encoded)

            ancestor = root / "redirect"
            ancestor.symlink_to(outside, target_is_directory=True)
            escaped = ancestor / "published.json"
            with self.assertRaises(gov.G0GovernanceError):
                collector._publish_or_reconcile_exact(
                    root, escaped, payload, label="synthetic ancestor"
                )
            self.assertFalse((outside / "published.json").exists())

    def test_bound_input_allows_only_exact_top_link_and_direct_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "workspace"
            target = base / "frozen-logs"
            other = base / "other-logs"
            root.mkdir()
            (target / "nested").mkdir(parents=True)
            (other / "nested").mkdir(parents=True)
            source = target / "nested/input.txt"
            source.write_text("bound input\n", encoding="utf-8")
            (other / "nested/input.txt").write_text("other\n", encoding="utf-8")
            (root / "logs").symlink_to(target, target_is_directory=True)
            with mock.patch.dict(
                publisher.SANCTIONED_INPUT_ROOT_TARGETS,
                {"logs": target},
                clear=True,
            ):
                record = publisher.direct_file_record_bound_input_rooted(
                    root, root / "logs/nested/input.txt", label="synthetic input"
                )
                self.assertEqual(record["sha256"], gov.sha256_bytes(b"bound input\n"))

                (root / "logs").unlink()
                (root / "logs").symlink_to(other, target_is_directory=True)
                with self.assertRaises(gov.G0GovernanceError):
                    publisher.direct_file_record_bound_input_rooted(
                        root, root / "logs/nested/input.txt", label="drifted root"
                    )

                (root / "logs").unlink()
                (root / "logs").symlink_to(target, target_is_directory=True)
                source.unlink()
                source.symlink_to(other / "nested/input.txt")
                with self.assertRaises(gov.G0GovernanceError):
                    publisher.direct_file_record_bound_input_rooted(
                        root, root / "logs/nested/input.txt", label="leaf link"
                    )

    def test_ros_stamp_preserves_epoch_nanoseconds_without_float_round_trip(self) -> None:
        class Stamp:
            secs = 1_700_000_000
            nsecs = 123_456_789

            def to_sec(self) -> float:
                raise AssertionError("float ROS timestamp path must not be used")

        observed = common_support_evaluator.ros_stamp_to_longdouble(Stamp())
        self.assertEqual(
            int(observed * common_support_evaluator.np.longdouble(1_000_000_000)),
            1_700_000_000_123_456_789,
        )
        lossy = common_support_evaluator.np.longdouble(
            float(Stamp.secs + Stamp.nsecs / 1_000_000_000)
        )
        self.assertNotEqual(observed, lossy)

        for invalid in (
            type("Missing", (), {"to_sec": lambda self: 0.0})(),
            type("BoolSecs", (), {"secs": True, "nsecs": 0})(),
            type("BadNsecs", (), {"secs": 1_700_000_000, "nsecs": 1_000_000_000})(),
        ):
            with self.subTest(invalid=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    common_support_evaluator.ros_stamp_to_longdouble(invalid)

    def test_g0_uses_frozen_sealed_interpreter_and_rejects_mutate_restore(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            interpreter = root / "external/python3.8"
            interpreter.parent.mkdir(parents=True)
            shutil.copy2(backend_runtime.PYTHON_INTERPRETER, interpreter)
            interpreter_bytes = interpreter.read_bytes()
            interpreter_record = {
                "path": os.fspath(interpreter),
                "sha256": hashlib.sha256(interpreter_bytes).hexdigest(),
                "size_bytes": len(interpreter_bytes),
            }
            execution_lock: dict[str, object] = {
                "external_runtime_bindings": {
                    "python_interpreter": interpreter_record,
                }
            }
            execution_lock["execution_lock_hash"] = gov.canonical_json_hash(
                execution_lock
            )
            execution_path = root / "papers/backend_execution_lock.json"
            write_json(execution_path, execution_lock)
            job = {
                "backend_execution_lock": gov.file_record(root, execution_path),
                "backend_execution_lock_hash": execution_lock[
                    "execution_lock_hash"
                ],
            }
            with mock.patch.dict(
                backend_runtime.EXTERNAL_RUNTIME_BINDING_PATHS,
                {"python_interpreter": interpreter},
                clear=False,
            ):
                with runner.sealed_python_interpreter(
                    job, root=root
                ) as (proc_path, descriptor):
                    completed = subprocess.run(
                        [proc_path, "-I", "-c", "print('SEALED_INTERPRETER')"],
                        pass_fds=(descriptor,),
                        env=backend_runtime.sanitized_child_environment(),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), "SEALED_INTERPRETER")

                original_stat = interpreter.stat()
                with self.assertRaisesRegex(
                    gov.G0GovernanceError, "interpreter lease failed"
                ):
                    with runner.sealed_python_interpreter(job, root=root):
                        interpreter.write_bytes(b"X" * len(interpreter_bytes))
                        interpreter.write_bytes(interpreter_bytes)
                        os.utime(
                            interpreter,
                            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                        )

    def test_reference_selection_locks_actual_samples_not_nominal_duration(self) -> None:
        origin = 1_703_000_000_000_000_000
        timestamps = [
            origin,
            origin + 44_999_000_000,
            origin + 45_005_000_000,
            origin + 74_996_300_000,
            origin + 75_001_000_000,
        ]
        first, last, count = references.select_relative_interval(
            timestamps, "45", "75"
        )
        self.assertEqual(first, origin + 45_005_000_000)
        self.assertEqual(last, origin + 74_996_300_000)
        self.assertEqual(count, 2)
        self.assertEqual(last - first, 29_991_300_000)
        with self.assertRaisesRegex(gov.G0GovernanceError, "exact to ns"):
            references.select_relative_interval(
                timestamps, "0.0000000001", "1"
            )

    def test_epoch_ns_ordering_and_subtraction_precede_float_conversion(self) -> None:
        fixture = json.loads(
            (FIXTURES / "p07_g0_epoch_ns_v1.json").read_text(encoding="utf-8")
        )
        start = int(fixture["window_start_ns"])
        sub_ulp = int(fixture["sub_float64_ulp_timestamp_ns"])
        end = int(fixture["window_end_ns"])
        self.assertEqual(
            collector.timestamp_token_to_ns(fixture["window_start_s_exact"])[0],
            start,
        )
        self.assertEqual(float(start / 1e9), float(sub_ulp / 1e9))
        with tempfile.TemporaryDirectory() as raw:
            trajectory = Path(raw) / "vio.csv"
            trajectory.write_text(
                "timestamp,x,y,z\n"
                f"{start},0,0,0\n"
                f"{sub_ulp},0,0,0\n"
                f"{end},0,0,0\n",
                encoding="utf-8",
            )
            observed = collector.inspect_trajectory(trajectory)
        self.assertTrue(observed["strictly_increasing"])
        self.assertEqual(observed["first_timestamp_ns"], start)
        self.assertEqual(observed["last_timestamp_ns"], end)
        self.assertEqual(end - start, fixture["expected_span_ns"])

    def test_queue_unknown_is_not_zero_and_does_not_hide_hard_failure(self) -> None:
        evidence = clean_evidence(
            run_id="fixture-p-r1",
            window_id="ntnu:fixture:0000",
            arm=evaluation.ARM_P,
            replay_index=1,
        )
        clean = evaluation.classify_replay_evidence(evidence)
        self.assertEqual(clean["classification_status"], "EVALUABLE")
        self.assertEqual(
            clean["queue_evidence_status"],
            "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
        )
        self.assertEqual(clean["queue_risk_codes"], [])

        evidence["trajectory"] = {"present": False, "row_count": 0}
        hard = evaluation.classify_replay_evidence(evidence)
        self.assertEqual(hard["classification_status"], "HARD_FAILURE")
        self.assertTrue(hard["hard_failure"])
        self.assertEqual(hard["incomplete_evidence_fields"], [])
        self.assertIn("EMPTY_TRAJECTORY", hard["observed_hard_failure_codes"])

        invalid = copy.deepcopy(evidence)
        invalid["queue"] = {
            "evidence_status": "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
            "drop_rate": 0.0,
            "backlog_growth_s": 0.0,
        }
        classified = evaluation.classify_replay_evidence(invalid)
        self.assertEqual(classified["classification_status"], "INCOMPLETE_EVIDENCE")
        self.assertIn(
            "queue.not_instrumented_values_must_be_null",
            classified["incomplete_evidence_fields"],
        )

    def test_production_shaped_terminal_audit_yields_exact_reference_coverage(self) -> None:
        fixture = json.loads(
            (FIXTURES / "p07_g0_epoch_ns_v1.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rows = queue_builder.build_queue_rows(
                fixture_snapshot(applicable_windows=0),
                allocated_at="2026-08-08T00:00:00+08:00",
                method_hashes=HASHES[:5],
            )
            row = {key: str(value) for key, value in rows[0].items()}
            start = int(fixture["window_start_ns"])
            end = int(fixture["window_end_ns"])
            trajectory = root / "artifacts/vio.csv"
            log = root / "artifacts/vins.log"
            trajectory.parent.mkdir(parents=True)
            trajectory.write_text(
                "timestamp,x,y,z\n"
                f"{start - 1_000_000_000},0,0,0\n"
                f"{start + 100},0,0,0\n"
                f"{start + 10_000_000_000},0,0,0\n"
                f"{end},0,0,0\n",
                encoding="utf-8",
            )
            log.write_text("normal terminal log\n", encoding="utf-8")
            audit_path = root / "audit_v1.json"
            audit = {
                "schema_version": collector.AUDIT_SCHEMA,
                "status": "PASS",
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": int(row["replay_index"]),
                "terminal": True,
                "terminal_process_status": "PASS_EXECUTION_ENVELOPE",
                "replay_hard_failure": False,
                "numeric_evaluation_candidate": True,
                "g0_evaluation_pending": True,
                "failure_code": None,
                "checks": {
                    "job_only_governed_adapter": True,
                    "job_authority_manifest_valid": True,
                    "data_identity_manifest_link_target_revalidated": True,
                    "durable_attempt_intent_and_state_chain_valid": True,
                    "expected_run_no_clobber": True,
                    "trajectory_values_read": False,
                    "ape_rpe_values_read": False,
                },
                "outcome_boundary": (
                    "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
                ),
                "output_structure": {
                    "trajectory": {
                        "exists": True,
                        "path": gov.display_path(root, trajectory),
                        "size_bytes": trajectory.stat().st_size,
                    },
                    "vins_log": {
                        "exists": True,
                        "path": gov.display_path(root, log),
                        "size_bytes": log.stat().st_size,
                    },
                },
                "technical_evidence": {
                    "process": {"exit_code": 0, "timed_out": False}
                },
            }
            write_json(audit_path, audit)
            reference_artifact = root / "reference.tum"
            reference_artifact.write_text("reference-only\n", encoding="utf-8")
            reference = {
                "kind": "tum",
                "path": gov.display_path(root, reference_artifact),
                "nominal_reference_rate_hz": 10.0,
                "nominal_estimate_rate_hz": 10.0,
                "window_start_s": float(start / 1e9),
                "window_end_s": float(end / 1e9),
                "window_start_ns": start,
                "window_end_ns": end,
                "max_reference_gap_s": 0.2,
                "max_estimate_gap_s": 0.2,
                "reference_time_offset_s": 0.0,
            }
            reference_record = {
                "reference_contract": reference,
                "reference_contract_hash": hashlib.sha256(b"reference").hexdigest(),
            }
            evidence = collector.build_failure_evidence(
                row,
                audit,
                root=root,
                audit_path=audit_path,
                reference_record=reference_record,
            )
            classified = evaluation.classify_replay_evidence(
                collector.classifier_input(evidence)
            )
        self.assertEqual(evidence["support"]["overlap_ns"], end - start)
        self.assertEqual(evidence["support"]["coverage_ratio"], 1.0)
        self.assertEqual(evidence["initialization"]["first_output_delay_ns"], 100)
        self.assertEqual(
            evidence["initialization"][
                "first_output_at_or_after_reference_start_ns"
            ],
            start + 100,
        )
        self.assertEqual(
            evidence["queue"]["evidence_status"],
            "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
        )
        self.assertEqual(classified["classification_status"], "EVALUABLE")


class P07PublisherTests(unittest.TestCase):
    def _intent(self, root: Path, name: str) -> dict[str, object]:
        token = hashlib.sha256(name.encode()).hexdigest()
        return publisher.build_publication_intent(
            root=root,
            job_id=f"fixture:{name}",
            job_hash=token,
            plan_hash=hashlib.sha256(b"plan").hexdigest(),
            evaluation_lock_hash=hashlib.sha256(b"lock").hexdigest(),
            backend_execution_lock_hash=hashlib.sha256(b"execution").hexdigest(),
            g0_execution_authority_hash=hashlib.sha256(b"authority").hexdigest(),
            evaluation_disposition="SKIP_NUMERIC_HARD_FAILURE",
            output_dir=root / "results" / name,
        )

    def test_transactional_formal_publisher_preserves_prepostguard_race_winner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "inputs/source.txt"
            output = root / "papers/p07/transaction.json"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            source.write_bytes(b"source\n")
            source_record = publisher.direct_file_record_rooted(
                root, source, label="transaction race source"
            )

            def publish_then_steal(
                publish_root: Path,
                relative: str,
                content: bytes,
                **kwargs: object,
            ) -> None:
                destination = publish_root / relative
                temporary = destination.with_name(
                    f".{destination.name}.partial.{os.getpid()}.fixture"
                )
                temporary.write_bytes(content)
                try:
                    kwargs["pre_link_guard"]()
                    os.link(temporary, destination)
                    destination.unlink()
                    destination.write_bytes(b"independent race winner\n")
                    kwargs["post_link_guard"]()
                finally:
                    temporary.unlink(missing_ok=True)

            with mock.patch.object(
                formal_io,
                "publish_bytes_no_clobber",
                side_effect=publish_then_steal,
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError, "not the staged inode"
                ):
                    publisher.publish_json_transactional_rooted(
                        root,
                        output,
                        {"fixture": True},
                        guard_records=[source_record],
                        validate=lambda: None,
                    )
            self.assertEqual(output.read_bytes(), b"independent race winner\n")
            self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

    def test_sealed_staging_reconcile_and_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "complete")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            ready = publisher.reconcile_publication(intent_path, root=root)
            self.assertEqual(
                ready["state"], "STAGING_COMPLETE_READY_FOR_ATOMIC_PUBLICATION"
            )
            applied = publisher.reconcile_publication(
                intent_path, root=root, apply=True
            )
            self.assertEqual(applied["state"], "STAGING_RECONCILED_AND_PUBLISHED")
            self.assertTrue(Path(str(intent["destination_absolute"])).is_dir())
            closed = publisher.reconcile_publication(intent_path, root=root)
            self.assertEqual(closed["state"], "ALREADY_CLOSED")
            with self.assertRaisesRegex(gov.G0GovernanceError, "already contains? evidence"):
                publisher.create_publication_intent(intent_path, intent, root=root)

    def test_incomplete_or_tampered_staging_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "tampered")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            (staging / publisher.BOUND_SUMMARY_NAME).write_text(
                '{"fixture": false}\n', encoding="utf-8"
            )
            observed = publisher.reconcile_publication(intent_path, root=root)
            self.assertEqual(
                observed["state"],
                "STAGING_INCOMPLETE_PRESERVED_MANUAL_REVIEW_REQUIRED",
            )
            self.assertTrue(staging.is_dir())
            self.assertFalse(Path(str(intent["destination_absolute"])).exists())

    def test_closeout_rejects_same_basename_record_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "closeout-record-substitution")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            closeout = publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )

            unrelated = root / "unrelated"
            unrelated.mkdir()
            (unrelated / publisher.RECEIPT_NAME).write_text(
                "unrelated receipt bytes\n", encoding="utf-8"
            )
            (unrelated / publisher.MANIFEST_NAME).write_text(
                "unrelated manifest bytes\n", encoding="utf-8"
            )
            altered = copy.deepcopy(closeout)
            altered["receipt"] = gov.file_record(
                root, unrelated / publisher.RECEIPT_NAME
            )
            altered["output_manifest"] = gov.file_record(
                root, unrelated / publisher.MANIFEST_NAME
            )
            altered["publication_closeout_hash"] = gov.canonical_json_hash(
                altered, "publication_closeout_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "exact destination record mismatch"
            ):
                publisher.validate_closeout(altered, intent=intent, root=root)

    def test_closeout_rejects_symlinked_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "closeout-symlink")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            destination = Path(str(intent["destination_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            closeout = publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )

            receipt = destination / publisher.RECEIPT_NAME
            external = root / "same-receipt-bytes.json"
            external.write_bytes(receipt.read_bytes())
            receipt.unlink()
            receipt.symlink_to(external)
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "not a direct single-link regular file|symlink forbidden",
            ):
                publisher.validate_closeout(closeout, intent=intent, root=root)

    def test_intent_rejects_symlinked_workspace_ancestor_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw)
            (root / "results").symlink_to(outside, target_is_directory=True)
            outside_intent_written = False
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "symlink component|direct directory"
            ):
                self._intent(root, "outside-intent")
            outside_intent_written = any(outside.iterdir())
            self.assertFalse(outside_intent_written, "OUTSIDE_INTENT_WRITTEN")

    def test_workspace_root_symlink_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            real = parent / "real"
            root = real / "ws"
            root.mkdir(parents=True)
            link = parent / "link"
            link.symlink_to(real, target_is_directory=True)
            linked_root = link / "ws"
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "root ancestor is not a direct directory"
            ):
                self._intent(linked_root, "root-ancestor-symlink")

    def test_closeout_rejects_destination_directory_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "destination-directory-symlink")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            destination = Path(str(intent["destination_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            closeout = publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )
            moved = destination.with_name(destination.name + "-moved")
            destination.rename(moved)
            destination.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "symlink component|direct result directory"
            ):
                publisher.validate_closeout(closeout, intent=intent, root=root)

    def test_sealed_result_rejects_same_bytes_payload_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "payload-symlink")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            destination = Path(str(intent["destination_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            closeout = publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )
            summary = destination / publisher.BOUND_SUMMARY_NAME
            same_bytes = root / "same-bound-summary-bytes.json"
            same_bytes.write_bytes(summary.read_bytes())
            summary.unlink()
            summary.symlink_to(same_bytes)
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "symlink forbidden in G0 result"
            ):
                publisher.validate_closeout(closeout, intent=intent, root=root)

    def test_closeout_rejects_rehashed_schema_literal_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "closeout-literal-tamper")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            closeout = publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )
            for field, value, message in (
                ("atomic_operation", "plain rename with replacement", "atomic operation"),
                ("outcome_boundary", "OUTCOME_READ_ALLOWED", "outcome boundary"),
            ):
                altered = copy.deepcopy(closeout)
                altered[field] = value
                altered["publication_closeout_hash"] = gov.canonical_json_hash(
                    altered, "publication_closeout_hash"
                )
                with self.assertRaisesRegex(gov.G0GovernanceError, message):
                    publisher.validate_closeout(altered, intent=intent, root=root)

    def test_intent_and_receipt_reject_rehashed_schema_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "schema-expansion")
            for label, mutate in (
                (
                    "policy",
                    lambda value: value["publication_policy"].__setitem__(
                        "destination_must_not_exist", False
                    ),
                ),
                (
                    "disposition",
                    lambda value: value.__setitem__(
                        "evaluation_disposition", "OUTCOME_READ_ALLOWED"
                    ),
                ),
                ("extra", lambda value: value.__setitem__("extra", True)),
            ):
                altered = copy.deepcopy(intent)
                mutate(altered)
                altered["publication_intent_hash"] = gov.canonical_json_hash(
                    altered, "publication_intent_hash"
                )
                with self.subTest(intent=label):
                    with self.assertRaises(gov.G0GovernanceError):
                        publisher.validate_publication_intent(altered, root=root)

            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            receipt = publisher.seal_staging_result(intent, root=root)
            altered_receipt = copy.deepcopy(receipt)
            altered_receipt["extra"] = True
            altered_receipt["result_receipt_hash"] = gov.canonical_json_hash(
                altered_receipt, "result_receipt_hash"
            )
            with self.assertRaisesRegex(gov.G0GovernanceError, "key set"):
                publisher.validate_result_receipt(altered_receipt, intent=intent)

    def test_sealed_snapshot_rejects_payload_change_between_inventories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "snapshot-race")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            summary = staging / publisher.BOUND_SUMMARY_NAME
            write_json(summary, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            original = publisher._inventory_open_result
            calls = 0

            def mutate_between(descriptor: int, *, durable: bool):
                nonlocal calls
                observed = original(descriptor, durable=durable)
                calls += 1
                if calls == 1:
                    summary.write_text('{"fixture": false}\n', encoding="utf-8")
                return observed

            with mock.patch.object(
                publisher, "_inventory_open_result", side_effect=mutate_between
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "retained-FD snapshots|manifest differs",
                ):
                    publisher.validate_sealed_result(
                        staging, intent=intent, root=root
                    )

    def test_retained_sealed_snapshot_rejects_mutate_use_restore(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "retained-result-mutate-restore")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            summary = staging / publisher.BOUND_SUMMARY_NAME
            write_json(summary, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            original = summary.read_bytes()
            original_stat = summary.stat()
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "changed during retained snapshot use",
            ):
                with publisher.retained_sealed_result_snapshot(
                    staging, intent=intent, root=root
                ) as (_receipt, _records, payload_bytes, _seal_bytes):
                    self.assertEqual(
                        payload_bytes[publisher.BOUND_SUMMARY_NAME], original
                    )
                    summary.write_bytes(b'{"fixture": false}\n')
                    summary.write_bytes(original)
                    os.utime(
                        summary,
                        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                    )

    def test_publish_retains_exact_staging_inode_and_sealed_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "publish-retained-inventory")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            destination = Path(str(intent["destination_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            summary = staging / publisher.BOUND_SUMMARY_NAME
            write_json(summary, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)

            original_rename = publisher._rename_retained_directory_noreplace_at

            def rewrite_self_consistent_seal_then_rename(
                parent: int,
                source_name: str,
                destination_name: str,
                source_fd: int,
            ) -> None:
                altered_bound = b'{"fixture": false}\n'
                summary.write_bytes(altered_bound)
                records = [
                    {
                        "path": publisher.BOUND_SUMMARY_NAME,
                        "sha256": hashlib.sha256(altered_bound).hexdigest(),
                        "size_bytes": len(altered_bound),
                    }
                ]
                manifest_bytes = gov.render_sha256_manifest(records)
                (staging / publisher.MANIFEST_NAME).write_bytes(manifest_bytes)
                receipt_path = staging / publisher.RECEIPT_NAME
                receipt = json.loads(receipt_path.read_bytes())
                receipt["payload_records"] = records
                receipt["output_manifest"] = {
                    "path": gov.display_path(
                        root, destination / publisher.MANIFEST_NAME
                    ),
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "size_bytes": len(manifest_bytes),
                }
                receipt["result_receipt_hash"] = gov.canonical_json_hash(
                    receipt, "result_receipt_hash"
                )
                write_json(receipt_path, receipt)
                original_rename(
                    parent, source_name, destination_name, source_fd
                )

            with mock.patch.object(
                publisher,
                "_rename_retained_directory_noreplace_at",
                side_effect=rewrite_self_consistent_seal_then_rename,
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "changed across atomic publication",
                ):
                    publisher.publish_staging(
                        intent, root=root, closeout_path=closeout_path
                    )
            self.assertTrue(destination.is_dir())
            self.assertFalse(closeout_path.exists())

    def test_publish_rejects_whole_staging_directory_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "publish-whole-directory-swap")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            moved = staging.with_name(staging.name + ".retained")
            with publisher.retained_workspace_directory(
                root, staging, label="fixture retained staging"
            ) as staging_fd:
                write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
                publisher.seal_staging_result_retained(
                    intent, root=root, staging_fd=staging_fd
                )
                staging.rename(moved)
                shutil.copytree(moved, staging)
                try:
                    with self.assertRaisesRegex(
                        gov.G0GovernanceError,
                        "differs from retained directory",
                    ):
                        publisher.publish_staging(
                            intent,
                            root=root,
                            closeout_path=closeout_path,
                            staging_fd=staging_fd,
                        )
                finally:
                    shutil.rmtree(staging)
                    moved.rename(staging)
            self.assertFalse(Path(str(intent["destination_absolute"])).exists())
            self.assertFalse(closeout_path.exists())

    def test_reconcile_rejects_closed_destination_with_recreated_staging(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "closed-with-staging")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )
            staging.mkdir()
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "contradictory staging/destination"
            ):
                publisher.reconcile_publication(intent_path, root=root)

    def test_reconcile_rejects_staging_created_during_final_state_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "closed-final-race")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            closeout_path = Path(str(intent["closeout_path_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            write_json(staging / publisher.BOUND_SUMMARY_NAME, {"fixture": True})
            publisher.seal_staging_result(intent, root=root)
            publisher.publish_staging(
                intent, root=root, closeout_path=closeout_path
            )
            original = publisher._leaf_state
            staging_observations = 0

            def race(root_value: Path, path: Path, *, label: str) -> str:
                nonlocal staging_observations
                if label == "publication staging":
                    staging_observations += 1
                    if staging_observations == 2:
                        staging.mkdir()
                return original(root_value, path, label=label)

            with mock.patch.object(publisher, "_leaf_state", side_effect=race):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError, "state changed during reconcile"
                ):
                    publisher.reconcile_publication(intent_path, root=root)

    def test_retained_staging_fd_prevents_ancestor_swap_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw)
            staging = root / "results/staging"
            staging.mkdir(parents=True)
            results = staging.parent
            moved = root / "results-moved"
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "no longer reachable|not a direct directory"
            ):
                with publisher.retained_workspace_directory(
                    root, staging, label="synthetic retained staging"
                ) as descriptor:
                    results.rename(moved)
                    results.symlink_to(outside, target_is_directory=True)
                    Path(f"/proc/self/fd/{descriptor}/child-output.json").write_text(
                        '{"safe": true}\n', encoding="utf-8"
                    )
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue((moved / "staging/child-output.json").is_file())

    def test_retained_staging_seal_rejects_same_name_directory_swap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "retained-seal-swap")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            moved = staging.with_name(staging.name + ".moved")
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "no longer reachable"
            ):
                with publisher.retained_workspace_directory(
                    root, staging, label="retained seal staging"
                ) as descriptor:
                    publisher.write_json_exclusive_retained_directory(
                        descriptor,
                        publisher.BOUND_SUMMARY_NAME,
                        {"fixture": True},
                        label="retained bound summary",
                    )
                    staging.rename(moved)
                    staging.mkdir()
                    write_json(
                        staging / publisher.BOUND_SUMMARY_NAME,
                        {"fixture": "attacker"},
                    )
                    publisher.seal_staging_result_retained(
                        intent, root=root, staging_fd=descriptor
                    )
            self.assertFalse((staging / publisher.RECEIPT_NAME).exists())
            self.assertFalse((moved / publisher.RECEIPT_NAME).exists())

    def test_retained_staging_write_and_seal_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            intent = self._intent(root, "retained-seal-success")
            intent_path = Path(str(intent["intent_path_absolute"]))
            staging = Path(str(intent["staging_absolute"]))
            publisher.create_publication_intent(intent_path, intent, root=root)
            staging.mkdir()
            with publisher.retained_workspace_directory(
                root, staging, label="retained seal staging"
            ) as descriptor:
                publisher.write_json_exclusive_retained_directory(
                    descriptor,
                    publisher.BOUND_SUMMARY_NAME,
                    {"fixture": True},
                    label="retained bound summary",
                )
                receipt = publisher.seal_staging_result_retained(
                    intent, root=root, staging_fd=descriptor
                )
            self.assertEqual(
                receipt["status"], publisher.RECEIPT_STATUS
            )
            publisher.validate_sealed_result(staging, intent=intent, root=root)


class P07ProductionShapedPlanAndReducerTests(unittest.TestCase):
    def _build_authority(
        self, root: Path, *, hard_first: bool = False
    ) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], Path]:
        logs_target = root / "_synthetic_sanctioned_logs_target"
        logs_target.mkdir()
        (root / "logs").symlink_to(logs_target, target_is_directory=True)
        sanctioned_logs_patch = mock.patch.dict(
            publisher.SANCTIONED_INPUT_ROOT_TARGETS,
            {"logs": logs_target},
            clear=False,
        )
        sanctioned_logs_patch.start()
        self.addCleanup(sanctioned_logs_patch.stop)
        raw_rows = queue_builder.build_queue_rows(
            fixture_snapshot(applicable_windows=0),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        rows = [{key: str(value) for key, value in item.items()} for item in raw_rows]
        protocol_path = root / "evaluator_protocol_v1.md"
        protocol_path.parent.mkdir(parents=True, exist_ok=True)
        protocol_path.write_bytes(
            (PROJECT_ROOT / epoch_builder.PROTOCOL_RELATIVE).read_bytes()
        )
        for relative in epoch_builder.ALLOWED_READ_PATHS:
            source = PROJECT_ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        epoch_payload = epoch_builder.build_lock(
            root=root,
            frozen_at="2026-08-08T00:00:00+08:00",
            require_output_absent=True,
        )
        epoch_path = root / epoch_builder.OUTPUT_RELATIVE
        write_json(epoch_path, epoch_payload)
        protocol_hash = gov.sha256_file(protocol_path)
        for row in rows:
            row["evaluator_protocol_sha256"] = protocol_hash
            row["evaluator_implementation_sha256"] = str(
                epoch_payload["corrected_implementation_binding"][
                    "implementation_bundle_sha256"
                ]
            )
            provenance = {
                "fixture_window_id": row["window_id"],
                "arm": row["arm"],
                "kind": "SYNTHETIC_PRODUCTION_SHAPED_SOURCE_V1",
            }
            row["source_provenance_hash"] = hashlib.sha256(
                json.dumps(
                    provenance,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
        queue_path = root / gov.REQUIRED_FROZEN_INPUT_PATHS["backend_queue"]
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        with queue_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        artifacts = root / "artifacts"
        artifacts.mkdir()
        start = 1_542_883_756_512_375_400
        end = start + 29_996_300_000
        trajectory = artifacts / "vio.csv"
        trajectory.write_text(
            f"{start},0,0,0\n{end},1,0,0\n", encoding="utf-8"
        )
        config = artifacts / "config.yaml"
        config.write_text("body_T_cam0: fixture\n", encoding="utf-8")
        reference_path = artifacts / "baseline.tum"
        reference_timestamps = [
            start + index * 45 * 1_000_000_000 for index in range(21)
        ]
        reference_path.write_text(
            "".join(
                f"{references.ns_to_decimal_seconds(timestamp)} "
                f"{index} 0 0 0 0 0 1\n"
                for index, timestamp in enumerate(reference_timestamps)
            ),
            encoding="utf-8",
        )
        reference_hash = gov.sha256_file(reference_path)
        reference_audit_path = root / "reference_audit.csv"
        audit_fields = [
            "dataset_family",
            "sequence",
            "reference_path",
            "reference_sha256",
            "nominal_reference_rate_hz",
            "nominal_estimate_rate_hz",
            "max_reference_gap_s",
            "max_estimate_interp_gap_s",
            "timestamp_offset_s",
        ]
        identities = sorted(
            {(row["dataset_family"], row["sequence"]) for row in rows}
        )
        with reference_audit_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=audit_fields)
            writer.writeheader()
            for family, sequence in identities:
                writer.writerow(
                    {
                        "dataset_family": family,
                        "sequence": sequence,
                        "reference_path": gov.display_path(root, reference_path),
                        "reference_sha256": reference_hash,
                        "nominal_reference_rate_hz": "10",
                        "nominal_estimate_rate_hz": "10",
                        "max_reference_gap_s": "0.2",
                        "max_estimate_interp_gap_s": "0.2",
                        "timestamp_offset_s": "0.0",
                    }
                )
        audit_file = artifacts / "audit.json"
        evidence_file = artifacts / "failure.json"
        classification_file = artifacts / "classification.json"
        for path in (audit_file, evidence_file, classification_file):
            write_json(path, {"fixture": path.stem})
        common_records = {
            "terminal_audit": gov.file_record(root, audit_file),
            "failure_evidence": gov.file_record(root, evidence_file),
            "classification": gov.file_record(root, classification_file),
            "trajectory": gov.file_record(root, trajectory),
            "config": gov.file_record(root, config),
            "reference": gov.file_record(root, reference_path),
        }
        counts = {
            "windows": 20,
            "applicable_d_windows": 0,
            "applicable_d_window_ids": [],
            "backend_algorithmic_replay_jobs": 240,
            "g0_evaluation_jobs": 180,
            "routes": {
                "B0_DESCRIPTIVE": 60,
                "P_VS_B1": 60,
                "P_VS_M": 60,
                "P_VS_D": 0,
            },
        }
        frozen_paths = {
            role: root / relative
            for role, relative in gov.REQUIRED_FROZEN_INPUT_PATHS.items()
        }
        for role, path in frozen_paths.items():
            if role not in {
                "backend_queue",
                "backend_allocation",
                "backend_queue_lock",
                "evaluator_precision_correction_lock",
                "evaluator_epoch_ns_correction_lock",
                "reference_contracts",
            }:
                payload: dict[str, object] = {"fixture_role": role}
                if role == "backend_queue_lock":
                    payload["backend_queue_lock_hash"] = gov.canonical_json_hash(
                        payload
                    )
                elif role == "evaluator_precision_correction_lock":
                    payload["correction_lock_hash"] = gov.canonical_json_hash(payload)
                elif role == "evaluator_epoch_ns_correction_lock":
                    payload["epoch_ns_correction_lock_hash"] = gov.canonical_json_hash(
                        payload
                    )
                write_json(path, payload)
        reference_records: list[dict[str, object]] = []
        reference_by_window: dict[str, dict[str, object]] = {}
        for window_id in sorted({row["window_id"] for row in rows}):
            window_row = next(row for row in rows if row["window_id"] == window_id)
            window_start, window_end, window_count = references.select_relative_interval(
                reference_timestamps,
                window_row["window_start_s"],
                window_row["window_end_s"],
            )
            reference = {
                "kind": "tum",
                "path": common_records["reference"]["path"],
                "nominal_reference_rate_hz": 10.0,
                "nominal_estimate_rate_hz": 10.0,
                "window_start_s": float(
                    references.ns_to_decimal_seconds(window_start)
                ),
                "window_end_s": float(
                    references.ns_to_decimal_seconds(window_end)
                ),
                "window_start_ns": window_start,
                "window_end_ns": window_end,
                "max_reference_gap_s": 0.2,
                "max_estimate_gap_s": 0.2,
                "reference_time_offset_s": 0.0,
            }
            reference_by_window[window_id] = reference
            record: dict[str, object] = {
                "window_id": window_id,
                "dataset_family": window_row["dataset_family"],
                "sequence": window_row["sequence"],
                "selection_relative_start_s": window_row["window_start_s"],
                "selection_relative_end_s": window_row["window_end_s"],
                "actual_reference_first_ns": window_start,
                "actual_reference_last_ns": window_end,
                "actual_reference_first_s_exact": references.ns_to_decimal_seconds(
                    window_start
                ),
                "actual_reference_last_s_exact": references.ns_to_decimal_seconds(
                    window_end
                ),
                "reference_samples_in_window": window_count,
                "reference_artifact": common_records["reference"],
                "reference_contract": reference,
                "derivation": (
                    "CHECKSUM_BOUND_BASELINE_TUM_FILTERED_BY_FROZEN_RELATIVE_INTERVAL"
                ),
            }
            record["reference_contract_hash"] = gov.canonical_json_hash(record)
            reference_records.append(record)
        reference_payload: dict[str, object] = {
            "schema_version": references.SCHEMA_VERSION,
            "status": references.STATUS,
            "windows": 20,
            "source_backend_queue": gov.file_record(root, queue_path),
            "contracts": reference_records,
            "reference_audit": gov.file_record(root, reference_audit_path),
            "checks": dict(references.CHECKS),
            "outcome_boundary": references.OUTCOME_BOUNDARY,
        }
        reference_payload["reference_contracts_hash"] = gov.canonical_json_hash(
            reference_payload
        )
        write_json(frozen_paths["reference_contracts"], reference_payload)
        reference_record_by_window = {
            str(record["window_id"]): record for record in reference_records
        }
        code_records: list[dict[str, object]] = []
        for role in sorted(gov.REQUIRED_CODE_BINDING_ROLES):
            path = root / gov.REQUIRED_CODE_BINDING_PATHS[role]
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# fixture {role}\n", encoding="utf-8")
            code_records.append({**gov.file_record(root, path), "role": role})
        reference_binding = gov.file_record(root, frozen_paths["reference_contracts"])
        protocol_hash = rows[0]["evaluator_protocol_sha256"]
        implementation_hash = str(
            epoch_payload["corrected_implementation_binding"][
                "implementation_bundle_sha256"
            ]
        )
        registry = (
            root
            / "papers/ieee_sensors_journal_experiments/run_registry.csv"
        )
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry_fields = [
            "run_id",
            "registry_event_id",
            "recorded_at",
            "supersedes_event_id",
            "status",
            "stage",
            "run_dir",
            "command_file",
            "input_hash_manifest",
            "output_hash_manifest",
            "infrastructure_failure",
            "replay_hard_failure",
            "algorithm_hard_failure",
            "notes",
        ]
        with registry.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=registry_fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "run_id": row["run_id"],
                        "registry_event_id": f"{row['run_id']}_e00",
                        "recorded_at": "2026-08-08T00:00:00+08:00",
                        "supersedes_event_id": "",
                        "status": "PLANNED",
                        "stage": "P07_BACKEND_REPLAY",
                        "run_dir": row["expected_run_dir"],
                        "command_file": "",
                        "input_hash_manifest": "",
                        "output_hash_manifest": "",
                        "infrastructure_failure": "",
                        "replay_hard_failure": "",
                        "algorithm_hard_failure": "",
                        "notes": "synthetic frozen pre-replay allocation",
                    }
                )
        source_evidence: list[dict[str, object]] = []
        for window_id, arm in sorted({(row["window_id"], row["arm"]) for row in rows}):
            row = next(
                item
                for item in rows
                if item["window_id"] == window_id and item["arm"] == arm
            )
            provenance = {
                "fixture_window_id": window_id,
                "arm": arm,
                "kind": "SYNTHETIC_PRODUCTION_SHAPED_SOURCE_V1",
            }
            source_evidence.append(
                {
                    "window_id": window_id,
                    "arm": arm,
                    "feature_bag": row["feature_bag"],
                    "feature_bag_sha256": row["feature_bag_sha256"],
                    "attestation_path": row["attestation_path"],
                    "attestation_sha256": row["attestation_sha256"],
                    "input_audit_path": row["input_audit_path"],
                    "input_audit_sha256": row["input_audit_sha256"],
                    "source_run_id": row["source_run_id"],
                    "source_provenance_kind": row["source_provenance_kind"],
                    "source_provenance_hash": row["source_provenance_hash"],
                    "source_provenance": provenance,
                }
            )
        queue_lock_payload: dict[str, object] = {
            "schema_version": "isj-p07-backend-queue-lock-v1",
            "status": "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK",
            "artifacts": [gov.file_record(root, queue_path)],
            "mutable_registry_prefix": gov.file_record(root, registry),
            "source_evidence": source_evidence,
        }
        queue_lock_payload["backend_queue_lock_hash"] = queue_builder.lock_hash(
            queue_lock_payload
        )
        write_json(frozen_paths["backend_queue_lock"], queue_lock_payload)
        allocation_rows = queue_builder.build_allocation_rows(
            rows,
            allocated_at="2026-08-08T00:00:00+08:00",
            backend_queue_lock_hash=str(
                queue_lock_payload["backend_queue_lock_hash"]
            ),
        )
        frozen_paths["backend_allocation"].write_bytes(
            queue_builder.render_csv(queue_builder.ALLOCATION_FIELDS, allocation_rows)
        )
        template = {
            "schema_version": "isj-p07-g0-evaluation-template-v1",
            "scientific_unit": "sequence_not_replay",
            "replay_indices": [1, 2, 3],
            "minimum_evaluable_replays": 2,
            "pairing_rule": "EQUAL_REPLAY_INDEX_ONLY",
            "routes": {
                "B0_DESCRIPTIVE": {
                    "route": evaluation.ROUTE_B0_DESCRIPTIVE,
                    "arms": [evaluation.ARM_B0],
                    "metric_role": evaluation.B0_METRIC_ROLE,
                },
                "P_VS_B1": {
                    "route": evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT,
                    "arms": [evaluation.ARM_P, evaluation.ARM_B1],
                },
                "P_VS_M": {
                    "route": evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT,
                    "arms": [evaluation.ARM_P, evaluation.ARM_M],
                },
                "P_VS_D": {
                    "route": evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT,
                    "arms": [evaluation.ARM_P, evaluation.ARM_D],
                    "conditional": True,
                },
            },
            "counts": counts,
            "reference_contracts": {
                "path": reference_binding["path"],
                "sha256": reference_binding["sha256"],
                "self_hash": reference_payload["reference_contracts_hash"],
                "absolute_window_rule": (
                    "FIRST_LAST_ACTUAL_REFERENCE_SAMPLE_AFTER_FROZEN_WINDOW_SELECTION"
                ),
                "relative_queue_seconds_as_epoch_forbidden": True,
                "same_window_all_arms_replays_exact": True,
            },
            "evaluator": {
                "profile_rule": "QUEUE_EVALUATOR_PROFILE_ID_EXACT",
                "protocol_sha256": protocol_hash,
                "implementation_bundle_sha256": implementation_hash,
                "rpe_delta_s": 1.0,
                "minimum_ape_poses": 30,
                "minimum_ape_span_s": 10.0,
                "minimum_common_coverage": 0.70,
                "minimum_rpe_pairs": 10,
            },
            "failure_policy": {
                "hard_failure_any_of_three": True,
                "solver_risk_any_of_three": True,
                "infrastructure_replacements_do_not_consume_algorithmic_slots": True,
                "hard_failure_precedes_numeric_effect": True,
                "queue_telemetry_policy": (
                    "QUEUE_TELEMETRY_NOT_INSTRUMENTED_NO_ZERO_IMPUTATION"
                ),
                "queue_risk_is_diagnostic_not_hard_failure": True,
                "queue_unknown_alone_does_not_make_replay_incomplete": True,
            },
        }
        lock: dict[str, object] = {
            "schema_version": gov.LOCK_SCHEMA,
            "status": gov.LOCK_STATUS,
            "frozen_at": "2026-08-08T00:00:00+08:00",
            "formalization_adoption": {
                "path": adoption.OUTPUT_RELATIVE,
                "sha256": "a" * 64,
                "size_bytes": 1,
                adoption.SELF_HASH_FIELD: "b" * 64,
            },
            "formalization_review_evidence": {
                "path": review_evidence.OUTPUT_RELATIVE,
                "sha256": "c" * 64,
                "size_bytes": 1,
                review_evidence.SELF_HASH_FIELD: "d" * 64,
            },
            "frozen_inputs": [
                {**gov.file_record(root, path), "role": role}
                for role, path in frozen_paths.items()
            ],
            "mutable_registry_prefix": gov.file_record(root, registry),
            "backend_bindings": {
                "queue_lock_self_hash": gov.read_json_object(
                    frozen_paths["backend_queue_lock"], label="fixture queue lock"
                )["backend_queue_lock_hash"],
                "precision_correction_self_hash": gov.read_json_object(
                    frozen_paths["evaluator_precision_correction_lock"],
                    label="fixture precision lock",
                )["correction_lock_hash"],
                "epoch_ns_correction_self_hash": gov.read_json_object(
                    frozen_paths["evaluator_epoch_ns_correction_lock"],
                    label="fixture epoch-ns lock",
                )["epoch_ns_correction_lock_hash"],
                "reference_contracts_self_hash": reference_payload[
                    "reference_contracts_hash"
                ],
            },
            "code_bindings": code_records,
            "evaluation_template": template,
            "evaluation_template_hash": gov.canonical_json_hash(template),
            "pre_first_replay_proof": {
                "registered_planned_runs": 240,
                "running_runs": 0,
                "terminal_runs": 0,
                "deterministic_outputs_existing": [],
            },
            "outcome_blind_audit": {
                "backend_replay_executed": False,
                "real_backend_trajectory_read": False,
                "ape_artifact_read": False,
                "rpe_artifact_read": False,
                "evaluator_executed": False,
                "result_artifact_read": False,
                "workspace_result_discovery_used": False,
            },
            "outcome_boundary": gov.LOCK_OUTCOME_BOUNDARY,
        }
        lock["evaluation_lock_hash"] = gov.canonical_json_hash(lock)
        lock_path = root / "g0_evaluation_lock_v1.json"
        write_json(lock_path, lock)
        expected_adoption = copy.deepcopy(lock["formalization_adoption"])

        def validate_fixture_adoption(value, *, root):
            if value != expected_adoption:
                raise adoption.AdoptionError("fixture adoption authority mismatch")
            return dict(value)

        adoption_patch = mock.patch.object(
            adoption,
            "validate_adoption_authority_binding",
            side_effect=validate_fixture_adoption,
        )
        adoption_patch.start()
        self.addCleanup(adoption_patch.stop)
        expected_evidence = copy.deepcopy(lock["formalization_review_evidence"])

        def validate_fixture_evidence(value, *, root):
            if value != expected_evidence:
                raise review_evidence.ReviewEvidenceError(
                    "fixture review-evidence authority mismatch"
                )
            return dict(value)

        evidence_patch = mock.patch.object(
            review_evidence,
            "validate_review_evidence_authority_binding",
            side_effect=validate_fixture_evidence,
        )
        evidence_patch.start()
        self.addCleanup(evidence_patch.stop)
        authority = gov.build_execution_authority_binding(lock_path, root=root)
        execution_lock: dict[str, object] = {
            "schema_version": "fixture-backend-execution-lock-v1",
            "status": "FIXTURE_FROZEN_READY",
            gov.EXECUTION_LOCK_BINDING_KEY: authority,
        }
        execution_lock["execution_lock_hash"] = gov.canonical_json_hash(
            execution_lock
        )
        execution_lock_path = root / "backend_replay_execution_lock_v1.json"
        write_json(execution_lock_path, execution_lock)
        # This large G0-only synthetic fixture predates the production backend
        # execution-lock fixture and intentionally supplies only the G0
        # authority projection.  Keep the production validator call wired, but
        # substitute this exact in-memory lock for the lifetime of the test;
        # dedicated backend tests exercise every strict execution-lock field.
        strict_execution_patch = mock.patch.object(
            backend_runtime,
            "validate_execution_lock",
            return_value=execution_lock,
        )
        strict_execution_patch.start()
        self.addCleanup(strict_execution_patch.stop)
        common_records["g0_evaluation_lock"] = gov.file_record(root, lock_path)
        common_records["backend_execution_lock"] = gov.file_record(
            root, execution_lock_path
        )
        evaluator_script_hash = next(
            str(record["sha256"])
            for record in code_records
            if record["role"] == "evaluator"
        )
        terminal_paths: list[Path] = []
        terminal_artifact_dir = root / "terminal_artifacts"
        terminal_artifact_dir.mkdir()
        classifier_record = next(
            record
            for record in code_records
            if record["role"] == "planner_classifier_reducer_primitives"
        )
        appended_registry_rows: list[dict[str, str]] = []
        for row in rows:
            replay_index = int(row["replay_index"])
            is_hard = hard_first and int(row["queue_index"]) == 1
            terminal_reference = reference_by_window[row["window_id"]]
            frozen_reference_record = reference_record_by_window[row["window_id"]]
            attempt_relative = row["expected_attempt_dir"]
            attempt_dir = root / attempt_relative
            attempt_dir.mkdir(parents=True, exist_ok=True)
            run_dir = root / row["expected_run_dir"]
            (run_dir / "vins_output").mkdir(parents=True, exist_ok=True)
            fixed_outputs = {
                "vins_log": run_dir / "vins.log",
                "vins_environment": run_dir / "vins_env_manifest.txt",
                "backend_replay_manifest": run_dir / "backend_replay_manifest.txt",
                "preparation_manifest": run_dir / "replay_manifest.txt",
            }
            for name, path in fixed_outputs.items():
                path.write_text(f"synthetic {name}\n", encoding="utf-8")
            trajectory_record: dict[str, object] | None = None
            trajectory_path = run_dir / "vins_output/vio.csv"
            if not is_hard:
                reference_start_ns = int(terminal_reference["window_start_ns"])
                reference_end_ns = int(terminal_reference["window_end_ns"])
                span_ns = reference_end_ns - reference_start_ns
                trajectory_timestamps = (
                    reference_start_ns,
                    reference_start_ns + span_ns // 3,
                    reference_start_ns + (2 * span_ns) // 3,
                    reference_end_ns,
                )
                trajectory_path.write_text(
                    "".join(
                        f"{timestamp},0,0,0,0,0,1\n"
                        for timestamp in trajectory_timestamps
                    ),
                    encoding="utf-8",
                )
                trajectory_record = gov.file_record(root, trajectory_path)
            expected_output_paths = {
                **fixed_outputs,
                "trajectory": trajectory_path,
                "ape_report": run_dir / "ape.txt",
                "rpe_report": run_dir / "rpe.txt",
                "ape_rpe_report": run_dir / "ape_rpe.json",
            }
            output_structure = {
                name: {
                    "path": os.fspath(path),
                    "exists": path.is_file(),
                    "size_bytes": path.stat().st_size if path.is_file() else None,
                }
                for name, path in expected_output_paths.items()
            }
            audit_path = attempt_dir / "audit_v1.json"
            audit_payload: dict[str, object] = {
                "schema_version": collector.AUDIT_SCHEMA,
                "status": "PASS",
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": replay_index,
                "terminal": True,
                "replay_hard_failure": is_hard,
                "numeric_evaluation_candidate": not is_hard,
                "g0_evaluation_pending": not is_hard,
                "failure_code": "EMPTY_TRAJECTORY" if is_hard else None,
                "terminal_process_status": "PASS_EXECUTION_ENVELOPE",
                "run_dir": gov.display_path(root, run_dir),
                "checks": {
                    "job_only_governed_adapter": True,
                    "job_authority_manifest_valid": True,
                    "data_identity_manifest_link_target_revalidated": True,
                    "durable_attempt_intent_and_state_chain_valid": True,
                    "expected_run_no_clobber": True,
                    "trajectory_values_read": False,
                    "ape_rpe_values_read": False,
                },
                "outcome_boundary": (
                    "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
                ),
                "output_structure": output_structure,
            }
            write_json(audit_path, audit_payload)
            audit_record = gov.file_record(root, audit_path)
            manifest_entries = {
                audit_record["path"]: audit_record["sha256"],
            }
            if trajectory_record is not None:
                manifest_entries[trajectory_record["path"]] = trajectory_record[
                    "sha256"
                ]
            if is_hard:
                backend_failure_path = attempt_dir / "failure_evidence.json"
                write_json(
                    backend_failure_path,
                    {
                        "schema_version": (
                            "isj-p07-backend-replay-failure-evidence-v1"
                        ),
                        "queue_index": int(row["queue_index"]),
                        "run_id": row["run_id"],
                        "failure_code": "EMPTY_TRAJECTORY",
                        "infrastructure_failure": False,
                    },
                )
                backend_failure_record = gov.file_record(root, backend_failure_path)
                manifest_entries[backend_failure_record["path"]] = (
                    backend_failure_record["sha256"]
                )
            output_manifest_path = attempt_dir / "output_hash_manifest.sha256"
            output_manifest_path.write_text(
                "".join(
                    f"{digest}  {relative}\n"
                    for relative, digest in sorted(manifest_entries.items())
                ),
                encoding="utf-8",
            )
            output_manifest_record = gov.file_record(root, output_manifest_path)
            terminal_registry_event = {
                "run_id": row["run_id"],
                "registry_event_id": f"{row['run_id']}_e02",
                "recorded_at": "2026-08-08T00:02:00+08:00",
                "supersedes_event_id": f"{row['run_id']}_e01",
                "status": "FAILED" if is_hard else "COMPLETED",
                "stage": "P07_BACKEND_REPLAY",
                "run_dir": row["expected_run_dir"],
                "command_file": f"{attempt_relative}/command.json",
                "input_hash_manifest": (
                    f"{attempt_relative}/input_hash_manifest.sha256"
                ),
                "output_hash_manifest": output_manifest_record["path"],
                "infrastructure_failure": "false",
                "replay_hard_failure": "true" if is_hard else "false",
                "algorithm_hard_failure": "true" if is_hard else "false",
                "notes": (
                    f"audit={audit_record['path']}; "
                    f"audit_sha256={audit_record['sha256']}; "
                    "output_manifest_sha256="
                    f"{output_manifest_record['sha256']}"
                ),
            }
            appended_registry_rows.extend(
                [
                    {
                        **terminal_registry_event,
                        "registry_event_id": f"{row['run_id']}_e01",
                        "recorded_at": "2026-08-08T00:01:00+08:00",
                        "supersedes_event_id": f"{row['run_id']}_e00",
                        "status": "RUNNING",
                        "output_hash_manifest": "",
                        "infrastructure_failure": "",
                        "replay_hard_failure": "",
                        "algorithm_hard_failure": "",
                        "notes": "synthetic governed running event",
                    },
                    terminal_registry_event,
                ]
            )
            terminal_provenance: dict[str, object] = {
                "schema_version": gov.TERMINAL_PROVENANCE_SCHEMA,
                "queue_index": int(row["queue_index"]),
                "base_queue_row": dict(row),
                "effective_queue_row": dict(row),
                "allowed_effective_row_overrides": sorted(
                    {
                        "run_id",
                        "runner_tag",
                        "expected_run_dir",
                        "expected_attempt_dir",
                    }
                ),
                "changed_effective_row_fields": [],
                "replacement_lock": None,
                "terminal_disposition": (
                    "ALGORITHM_HARD_FAILURE" if is_hard else "COMPLETED"
                ),
                "terminal_registry_event": terminal_registry_event,
                "terminal_registry_event_sha256": gov.canonical_json_hash(
                    terminal_registry_event
                ),
                "output_manifest": output_manifest_record,
                "terminal_audit_path": audit_record["path"],
                "outcome_boundary": (
                    "BACKEND_CONTROLLER_TERMINAL_AUTHORITY_NO_APE_RPE_RESULT_READ"
                ),
            }
            terminal_provenance["terminal_provenance_hash"] = (
                gov.canonical_json_hash(terminal_provenance)
            )
            failure_evidence = collector.build_failure_evidence(
                row,
                audit_payload,
                root=root,
                audit_path=audit_path,
                audit_record=audit_record,
                reference_record=frozen_reference_record,
                governance_authority={
                    "evaluation_lock_hash": lock["evaluation_lock_hash"],
                    "backend_execution_lock_hash": execution_lock[
                        "execution_lock_hash"
                    ],
                    "g0_execution_authority_hash": authority[
                        "g0_execution_authority_hash"
                    ],
                },
                terminal_provenance=terminal_provenance,
            )
            failure_path = terminal_artifact_dir / (
                f"q{int(row['queue_index']):03d}.failure.json"
            )
            write_json(failure_path, failure_evidence)
            failure_record = gov.file_record(root, failure_path)
            wrapper = collector.build_classification(
                failure_evidence,
                evidence_record=failure_record,
                classifier_record=classifier_record,
            )
            classification_path = terminal_artifact_dir / (
                f"q{int(row['queue_index']):03d}.classification.json"
            )
            write_json(classification_path, wrapper)
            classification_record = gov.file_record(root, classification_path)
            core = wrapper["classification"]
            assert isinstance(core, dict)
            terminal: dict[str, object] = {
                "schema_version": gov.TERMINAL_BINDING_SCHEMA,
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": replay_index,
                "backend_algorithmic_slot": row["algorithmic_slot"],
                "source_run_id": row["source_run_id"],
                "source_provenance_kind": row["source_provenance_kind"],
                "source_provenance_hash": row["source_provenance_hash"],
                "algorithmic_slot": True,
                "terminal": True,
                "evaluation_lock_hash": lock["evaluation_lock_hash"],
                "backend_execution_lock_hash": execution_lock[
                    "execution_lock_hash"
                ],
                "g0_execution_authority_hash": authority[
                    "g0_execution_authority_hash"
                ],
                "classification": wrapper,
                "backend_terminal_provenance": terminal_provenance,
                "artifact_bindings": {
                    **common_records,
                    "terminal_audit": audit_record,
                    "failure_evidence": failure_record,
                    "classification": classification_record,
                    "trajectory": trajectory_record,
                },
                "reference": terminal_reference,
                "reference_contract_hash": frozen_reference_record[
                    "reference_contract_hash"
                ],
                "arm_time_offset_s": 0.0,
                "evaluator_profile_id": row["evaluator_profile_id"],
                "evaluator_protocol_sha256": row["evaluator_protocol_sha256"],
                "evaluator_script_sha256": evaluator_script_hash,
                "outcome_boundary": gov.OUTCOME_BOUNDARY,
            }
            terminal["terminal_binding_hash"] = gov.canonical_json_hash(terminal)
            path = (
                root
                / row["expected_attempt_dir"]
                / "g0_terminal_binding_v1.json"
            )
            write_json(path, terminal)
            terminal_paths.append(path)
        with registry.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=registry_fields)
            writer.writerows(appended_registry_rows)
        terminal_index = materializer.build_terminal_index(terminal_paths, root=root)
        self._last_terminal_index = terminal_index
        terminal_index_path = root / "terminal_index.json"
        write_json(terminal_index_path, terminal_index)
        self._last_terminal_index_path = terminal_index_path
        plan, jobs = materializer.materialize_plan(
            lock,
            terminal_index,
            root=root,
            job_root=root / "jobs",
            result_root_relative="results/g0",
            terminal_index_path=terminal_index_path,
        )
        return lock, plan, jobs, queue_path

    @staticmethod
    def _numeric_summary(core: dict[str, object]) -> dict[str, object]:
        arms = core["arms"]
        assert isinstance(arms, dict)
        reference = core["reference"]
        assert isinstance(reference, dict)
        return {
            "protocol": {
                "contrast_name": core["contrast_name"],
                "reference": dict(reference),
                "evaluation_rate_hz": 10.0,
                "nominal_reference_rate_hz": reference[
                    "nominal_reference_rate_hz"
                ],
                "nominal_estimate_rate_hz": reference[
                    "nominal_estimate_rate_hz"
                ],
                "window_start_s": reference["window_start_s"],
                "window_end_s": reference["window_end_s"],
                "max_reference_gap_s": reference["max_reference_gap_s"],
                "max_estimate_gap_s": reference["max_estimate_gap_s"],
                "rpe_delta_s": 1.0,
                "body_to_camera_applied": True,
                "rpe_semantics": "aligned_global_frame_positional_delta",
                "reference_time_offset_s": reference[
                    "reference_time_offset_s"
                ],
                "arm_time_offsets_s": {arm: 0.0 for arm in arms},
            },
            "support": {
                "grid_count": 100,
                "matched_count": 95,
                "common_span_s": 30.0,
                "common_coverage": 0.95,
                "segment_count": 1,
                "rpe_pairs": 90,
                "rpe_valid": True,
                "ape_valid": True,
                "window_duration_s": 45.0,
            },
            "reference": {
                "audit": {},
                "rejection_histogram": {},
                "valid_grid_count": 100,
                "bracket_gap_p50_s": 0.1,
                "bracket_gap_p95_s": 0.1,
                "bracket_gap_max_s": 0.1,
            },
            "arms": {
                arm: {
                    "rpe_rmse_m": 0.8 + index * 0.1,
                    "ape_rmse_m": 1.0 + index * 0.1,
                }
                for index, arm in enumerate(sorted(arms))
            },
        }

    @staticmethod
    def _index_after_terminal_rewrite(
        root: Path,
        terminal_index: dict[str, object],
        terminal_path: Path,
        terminal: dict[str, object],
    ) -> dict[str, object]:
        write_json(terminal_path, terminal)
        altered_index = copy.deepcopy(terminal_index)
        binding = next(
            record
            for record in altered_index["bindings"]
            if record["path"] == gov.display_path(root, terminal_path)
        )
        binding.update(gov.file_record(root, terminal_path))
        binding["terminal_binding_hash"] = terminal["terminal_binding_hash"]
        altered_index["terminal_index_hash"] = gov.canonical_json_hash(
            altered_index, "terminal_index_hash"
        )
        write_json(root / "terminal_index.json", altered_index)
        return altered_index

    def test_materializer_rejects_rehashed_terminal_reference_classification_and_offset(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            terminal_index = copy.deepcopy(self._last_terminal_index)
            index_record = terminal_index["bindings"][0]
            terminal_path = root / str(index_record["path"])
            original_terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            classification_path = root / str(
                original_terminal["artifact_bindings"]["classification"]["path"]
            )
            original_classification = json.loads(
                classification_path.read_text(encoding="utf-8")
            )

            altered = copy.deepcopy(original_terminal)
            reference = altered["reference"]
            fake_start = int(reference["window_start_ns"]) + 1
            fake_end = int(reference["window_end_ns"]) - 1
            reference["window_start_ns"] = fake_start
            reference["window_end_ns"] = fake_end
            reference["window_start_s"] = float(
                references.ns_to_decimal_seconds(fake_start)
            )
            reference["window_end_s"] = float(
                references.ns_to_decimal_seconds(fake_end)
            )
            altered["reference_contract_hash"] = gov.canonical_json_hash(
                {"window_id": altered["window_id"], "reference": reference}
            )
            altered["terminal_binding_hash"] = gov.canonical_json_hash(
                altered, "terminal_binding_hash"
            )
            altered_index = self._index_after_terminal_rewrite(
                root, terminal_index, terminal_path, altered
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "reference hash/contract/artifact differs",
            ):
                materializer.materialize_plan(
                    lock,
                    altered_index,
                    root=root,
                    job_root=root / "attack_jobs_reference",
                    result_root_relative="attack_results/reference",
                    terminal_index_path=root / "terminal_index.json",
                )

            write_json(terminal_path, original_terminal)
            altered = copy.deepcopy(original_terminal)
            wrapper = altered["classification"]
            core = wrapper["classification"]
            self.assertEqual(core["classification_status"], "EVALUABLE")
            core["queue_risk_codes"] = ["SUSTAINED_QUEUE_DROP"]
            wrapper["classification_hash"] = gov.canonical_json_hash(
                wrapper, "classification_hash"
            )
            altered["terminal_binding_hash"] = gov.canonical_json_hash(
                altered, "terminal_binding_hash"
            )
            altered_index = self._index_after_terminal_rewrite(
                root, terminal_index, terminal_path, altered
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "embedded classification differs from bound artifact",
            ):
                materializer.materialize_plan(
                    lock,
                    altered_index,
                    root=root,
                    job_root=root / "attack_jobs_embedded_classification",
                    result_root_relative="attack_results/embedded_classification",
                    terminal_index_path=root / "terminal_index.json",
                )

            write_json(terminal_path, original_terminal)
            altered = copy.deepcopy(original_terminal)
            wrapper = altered["classification"]
            core = wrapper["classification"]
            core["queue_risk_codes"] = ["SUSTAINED_QUEUE_DROP"]
            wrapper["classification_hash"] = gov.canonical_json_hash(
                wrapper, "classification_hash"
            )
            write_json(classification_path, wrapper)
            altered["artifact_bindings"]["classification"] = gov.file_record(
                root, classification_path
            )
            altered["terminal_binding_hash"] = gov.canonical_json_hash(
                altered, "terminal_binding_hash"
            )
            altered_index = self._index_after_terminal_rewrite(
                root, terminal_index, terminal_path, altered
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "frozen-classifier recomputation",
            ):
                materializer.materialize_plan(
                    lock,
                    altered_index,
                    root=root,
                    job_root=root / "attack_jobs_evaluable",
                    result_root_relative="attack_results/evaluable",
                    terminal_index_path=root / "terminal_index.json",
                )

            write_json(classification_path, original_classification)
            write_json(terminal_path, original_terminal)
            altered = copy.deepcopy(original_terminal)
            altered["arm_time_offset_s"] = 0.25
            altered["terminal_binding_hash"] = gov.canonical_json_hash(
                altered, "terminal_binding_hash"
            )
            altered_index = self._index_after_terminal_rewrite(
                root, terminal_index, terminal_path, altered
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "zero-offset protocol",
            ):
                materializer.materialize_plan(
                    lock,
                    altered_index,
                    root=root,
                    job_root=root / "attack_jobs_offset",
                    result_root_relative="attack_results/offset",
                    terminal_index_path=root / "terminal_index.json",
                )

    def test_materializer_rejects_rehashed_hard_failure_classification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(
                root, hard_first=True
            )
            terminal_index = copy.deepcopy(self._last_terminal_index)
            index_record = terminal_index["bindings"][0]
            terminal_path = root / str(index_record["path"])
            altered = json.loads(terminal_path.read_text(encoding="utf-8"))
            wrapper = altered["classification"]
            core = wrapper["classification"]
            self.assertEqual(core["classification_status"], "HARD_FAILURE")
            core["solver_risk_codes"] = ["SYNTHETIC_REHASHED_RISK"]
            core["solver_risk"] = True
            wrapper["classification_hash"] = gov.canonical_json_hash(
                wrapper, "classification_hash"
            )
            classification_path = root / str(
                altered["artifact_bindings"]["classification"]["path"]
            )
            write_json(classification_path, wrapper)
            altered["artifact_bindings"]["classification"] = gov.file_record(
                root, classification_path
            )
            altered["terminal_binding_hash"] = gov.canonical_json_hash(
                altered, "terminal_binding_hash"
            )
            altered_index = self._index_after_terminal_rewrite(
                root, terminal_index, terminal_path, altered
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "frozen-classifier recomputation",
            ):
                materializer.materialize_plan(
                    lock,
                    altered_index,
                    root=root,
                    job_root=root / "attack_jobs_hard",
                    result_root_relative="attack_results/hard",
                    terminal_index_path=root / "terminal_index.json",
                )

    def test_terminal_rejects_rehashed_failure_evidence_not_derived_from_audit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._build_authority(root)
            terminal_record = self._last_terminal_index["bindings"][0]
            terminal_path = root / str(terminal_record["path"])
            original_terminal = json.loads(
                terminal_path.read_text(encoding="utf-8")
            )
            failure_path = root / str(
                original_terminal["artifact_bindings"]["failure_evidence"]["path"]
            )
            classification_path = root / str(
                original_terminal["artifact_bindings"]["classification"]["path"]
            )
            original_failure = json.loads(
                failure_path.read_text(encoding="utf-8")
            )
            original_classification = json.loads(
                classification_path.read_text(encoding="utf-8")
            )
            classifier_record = original_classification[
                "classifier_implementation"
            ]

            def trajectory_tamper(value: dict[str, object]) -> None:
                value["trajectory"]["row_count"] += 1

            def initialization_tamper(value: dict[str, object]) -> None:
                value["initialization"]["first_output_delay_ns"] += 1

            def support_tamper(value: dict[str, object]) -> None:
                value["support"]["overlap_ns"] -= 1

            def process_tamper(value: dict[str, object]) -> None:
                value["process"]["exit_code"] = 1

            def queue_tamper(value: dict[str, object]) -> None:
                value["queue"] = {
                    "evidence_status": "MEASURED",
                    "drop_rate": 0.0,
                    "backlog_growth_s": 0.0,
                }

            def solver_tamper(value: dict[str, object]) -> None:
                value["solver_log_text"] = "synthetic unbound solver text"
                value["solver_log_artifact"] = copy.deepcopy(
                    original_terminal["artifact_bindings"]["config"]
                )

            def extra_key_tamper(value: dict[str, object]) -> None:
                value["rehash_extra"] = True

            mutations = (
                ("trajectory", trajectory_tamper),
                ("initialization", initialization_tamper),
                ("support", support_tamper),
                ("process", process_tamper),
                ("queue", queue_tamper),
                ("solver_log", solver_tamper),
                ("extra_key", extra_key_tamper),
            )
            for label, mutate in mutations:
                with self.subTest(failure_evidence_tamper=label):
                    altered_failure = copy.deepcopy(original_failure)
                    mutate(altered_failure)
                    altered_failure["failure_evidence_hash"] = (
                        gov.canonical_json_hash(
                            altered_failure, "failure_evidence_hash"
                        )
                    )
                    write_json(failure_path, altered_failure)
                    failure_record = gov.file_record(root, failure_path)
                    altered_classification = collector.build_classification(
                        altered_failure,
                        evidence_record=failure_record,
                        classifier_record=classifier_record,
                    )
                    write_json(classification_path, altered_classification)
                    altered_terminal = copy.deepcopy(original_terminal)
                    altered_terminal["classification"] = altered_classification
                    altered_terminal["artifact_bindings"][
                        "failure_evidence"
                    ] = failure_record
                    altered_terminal["artifact_bindings"][
                        "classification"
                    ] = gov.file_record(root, classification_path)
                    altered_terminal["terminal_binding_hash"] = (
                        gov.canonical_json_hash(
                            altered_terminal, "terminal_binding_hash"
                        )
                    )
                    with self.assertRaisesRegex(
                        gov.G0GovernanceError,
                        "failure evidence .*keys differ|"
                        "failure evidence differs from deterministic",
                    ):
                        gov.validate_terminal_binding(
                            altered_terminal, root=root, verify_files=True
                        )
                    write_json(failure_path, original_failure)
                    write_json(classification_path, original_classification)

            audit_path = root / str(
                original_terminal["artifact_bindings"]["terminal_audit"]["path"]
            )
            original_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            redirected_audit = copy.deepcopy(original_audit)
            canonical_trajectory = Path(
                redirected_audit["output_structure"]["trajectory"]["path"]
            )
            redirected_trajectory = canonical_trajectory.with_name(
                "same-bytes-redirected-vio.csv"
            )
            redirected_trajectory.write_bytes(canonical_trajectory.read_bytes())
            redirected_audit["output_structure"]["trajectory"]["path"] = (
                os.fspath(redirected_trajectory)
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "output structure trajectory path differs",
            ):
                gov._validate_terminal_audit_output_authority(
                    redirected_audit,
                    root=root,
                    effective_queue_row=original_terminal[
                        "backend_terminal_provenance"
                    ]["effective_queue_row"],
                )

    def test_rehashed_extra_keys_are_rejected_across_g0_authority_plan_job_summary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, plan, jobs, _queue_path = self._build_authority(root)
            job = jobs[0]

            indexed_terminal_record = self._last_terminal_index["bindings"][0]
            indexed_terminal_path = root / str(indexed_terminal_record["path"])
            indexed_terminal = json.loads(
                indexed_terminal_path.read_text(encoding="utf-8")
            )
            with mock.patch.object(
                backend_runtime,
                "validate_execution_lock",
                side_effect=backend_runtime.BackendReplayViolation(
                    "synthetic strict runtime artifact deletion"
                ),
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "strict semantic validation",
                ):
                    gov.validate_terminal_binding(
                        indexed_terminal, root=root, verify_files=True
                    )

            fake_controller = mock.Mock()
            wrong_effective = copy.deepcopy(
                indexed_terminal["backend_terminal_provenance"][
                    "effective_queue_row"
                ]
            )
            wrong_effective["run_id"] = "not-controller-selected"
            fake_controller._replacement_for_index.return_value = (
                wrong_effective,
                None,
            )
            with mock.patch.object(
                gov, "_backend_controller_module", return_value=fake_controller
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "controller-selected latest",
                ):
                    gov.validate_terminal_binding(
                        indexed_terminal, root=root, verify_files=True
                    )
            registry_path = root / str(lock["mutable_registry_prefix"]["path"])
            registry_original = registry_path.read_bytes()
            with registry_path.open(newline="", encoding="utf-8") as handle:
                registry_reader = csv.DictReader(handle)
                registry_fields = list(registry_reader.fieldnames or [])
                registry_rows = list(registry_reader)
            running_row = next(
                row
                for row in registry_rows
                if row["run_id"] == indexed_terminal["run_id"]
                and row["status"] == "RUNNING"
            )
            running_row["supersedes_event_id"] = "tampered_parent_event"
            with registry_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=registry_fields)
                writer.writeheader()
                writer.writerows(registry_rows)
            try:
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "canonical registry chain is invalid",
                ):
                    gov.validate_terminal_binding(
                        indexed_terminal, root=root, verify_files=True
                    )
            finally:
                registry_path.write_bytes(registry_original)

            # The production-shaped authority was fully validated while it
            # was built, and the three targeted terminal-authority attacks
            # above exercised the live validator.  The remaining cases in
            # this method are plan/job/summary schema-rehash attacks; avoid
            # redoing 240 expensive reference/registry validations for every
            # independent static mutation while still checking each bound
            # terminal self-hash and deterministic core rebuild.
            cached_terminal_validation = mock.patch.object(
                gov,
                "validate_terminal_binding",
                side_effect=lambda value, **_kwargs: gov.validate_self_hash(
                    value,
                    "terminal_binding_hash",
                    label="cached validated terminal fixture",
                ),
            )
            cached_terminal_validation.start()
            self.addCleanup(cached_terminal_validation.stop)

            execution_path = root / str(job["backend_execution_lock"]["path"])
            execution_lock = json.loads(execution_path.read_text(encoding="utf-8"))
            authority = copy.deepcopy(execution_lock[gov.EXECUTION_LOCK_BINDING_KEY])
            authority["rehash_extra"] = True
            authority["g0_execution_authority_hash"] = gov.canonical_json_hash(
                authority, "g0_execution_authority_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "execution authority keys differ"
            ):
                gov.validate_execution_authority_binding(authority, root=root)

            authority = copy.deepcopy(execution_lock[gov.EXECUTION_LOCK_BINDING_KEY])
            authority["evaluation_lock"]["rehash_extra"] = True
            authority["g0_execution_authority_hash"] = gov.canonical_json_hash(
                authority, "g0_execution_authority_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "evaluation lock keys differ"
            ):
                gov.validate_execution_authority_binding(authority, root=root)

            altered_plan = copy.deepcopy(plan)
            altered_plan["rehash_extra"] = True
            altered_plan["plan_hash"] = gov.canonical_json_hash(
                altered_plan, "plan_hash"
            )
            with self.assertRaisesRegex(gov.G0GovernanceError, "G0 plan keys differ"):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_plan = copy.deepcopy(plan)
            altered_plan["plan_basis"]["rehash_extra"] = True
            altered_plan["plan_basis_hash"] = gov.canonical_json_hash(
                altered_plan["plan_basis"]
            )
            altered_plan["plan_hash"] = gov.canonical_json_hash(
                altered_plan, "plan_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "G0 plan basis keys differ"
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            def rehash_plan(candidate: dict[str, object]) -> None:
                candidate["plan_basis_hash"] = gov.canonical_json_hash(
                    candidate["plan_basis"]
                )
                candidate["plan_hash"] = gov.canonical_json_hash(
                    candidate, "plan_hash"
                )

            altered_plan = copy.deepcopy(plan)
            hashes = altered_plan["plan_basis"]["terminal_binding_hashes"]
            hashes[1] = hashes[0]
            rehash_plan(altered_plan)
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "terminal-binding hashes are invalid"
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_plan = copy.deepcopy(plan)
            altered_plan["plan_basis"]["terminal_index_hash"] = "f" * 64
            rehash_plan(altered_plan)
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "terminal-index authority differs"
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_plan = copy.deepcopy(plan)
            altered_plan["plan_basis"]["terminal_index_file"] = None
            rehash_plan(altered_plan)
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "terminal-index file record differs"
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_plan = copy.deepcopy(plan)
            altered_plan["plan_basis"]["core_job_hashes"][0] = "e" * 64
            altered_plan["plan_basis"]["core_jobs_hash"] = gov.canonical_json_hash(
                {"core_job_hashes": altered_plan["plan_basis"]["core_job_hashes"]}
            )
            rehash_plan(altered_plan)
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "membership/core-job hashes differ|deterministic terminal-index rebuild",
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_plan = copy.deepcopy(plan)
            routes = altered_plan["counts"]["routes"]
            route_names = sorted(routes)
            routes[route_names[0]] -= 1
            routes[route_names[1]] += 1
            altered_plan["plan_hash"] = gov.canonical_json_hash(
                altered_plan, "plan_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "count details differ"
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            for field, value in (
                ("job_id", "synthetic_rehashed_job_id"),
                ("contrast_name", "SYNTHETIC_REHASHED_CONTRAST"),
                ("output_dir_absolute", os.fspath(root / "results/alternate")),
            ):
                altered_plan = copy.deepcopy(plan)
                altered_plan["jobs"][0][field] = value
                altered_plan["plan_hash"] = gov.canonical_json_hash(
                    altered_plan, "plan_hash"
                )
                with self.subTest(deterministic_membership=field):
                    with self.assertRaisesRegex(
                        gov.G0GovernanceError,
                        "deterministic G0 plan membership|core jobs differ",
                    ):
                        gov.validate_plan_payload(
                            altered_plan, lock=lock, root=root
                        )

            cloned_terminal = root / "cloned_same_slot_terminal.json"
            cloned_terminal.write_bytes(indexed_terminal_path.read_bytes())
            cloned_index = copy.deepcopy(self._last_terminal_index)
            cloned_index["bindings"][0].update(
                gov.file_record(root, cloned_terminal)
            )
            cloned_index["terminal_index_hash"] = gov.canonical_json_hash(
                cloned_index, "terminal_index_hash"
            )
            cloned_index_path = root / "cloned_terminal_index.json"
            write_json(cloned_index_path, cloned_index)
            altered_plan = copy.deepcopy(plan)
            altered_plan["plan_basis"]["terminal_index_hash"] = cloned_index[
                "terminal_index_hash"
            ]
            altered_plan["plan_basis"]["terminal_index_file"] = gov.file_record(
                root, cloned_index_path
            )
            altered_plan["plan_basis_hash"] = gov.canonical_json_hash(
                altered_plan["plan_basis"]
            )
            altered_plan["plan_hash"] = gov.canonical_json_hash(
                altered_plan, "plan_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "canonical effective-attempt binding",
            ):
                gov.validate_plan_payload(altered_plan, lock=lock, root=root)

            altered_job = copy.deepcopy(job)
            altered_job["rehash_extra"] = True
            altered_job["job_hash"] = gov.canonical_json_hash(
                altered_job, "job_hash"
            )
            with self.assertRaisesRegex(gov.G0GovernanceError, "G0 job keys differ"):
                gov.validate_job_payload(
                    altered_job,
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_inputs=False,
                )

            altered_job = copy.deepcopy(job)
            altered_job["evaluation_job"]["rehash_extra"] = True
            altered_job["job_hash"] = gov.canonical_json_hash(
                altered_job, "job_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "scientific evaluation job keys differ"
            ):
                gov.validate_job_payload(
                    altered_job,
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_inputs=False,
                )

            altered_job = copy.deepcopy(job)
            scientific_arm = next(iter(altered_job["evaluation_job"]["arms"]))
            altered_job["evaluation_job"]["arms"][scientific_arm][
                "classification"
            ]["queue_risk_codes"] = ["SUSTAINED_QUEUE_DROP"]
            altered_job["job_hash"] = gov.canonical_json_hash(
                altered_job, "job_hash"
            )
            altered_plan = copy.deepcopy(plan)
            membership = next(
                record
                for record in altered_plan["jobs"]
                if record["job_id"] == altered_job["job_id"]
            )
            membership["job_hash"] = altered_job["job_hash"]
            altered_plan["plan_hash"] = gov.canonical_json_hash(
                altered_plan, "plan_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "core-job|exact terminal provenance|job membership identity mismatch",
            ):
                gov.validate_job_payload(
                    altered_job,
                    plan=altered_plan,
                    lock=lock,
                    root=root,
                    verify_inputs=False,
                )

            core = job["evaluation_job"]
            summary = self._numeric_summary(core)
            staging = root / "synthetic_bound_summary_staging"
            staging.mkdir()
            write_json(staging / "common_support_summary.json", summary)
            bound = runner.build_bound_summary(
                job,
                plan,
                lock,
                root=root,
                staging=staging,
                numeric_summary=summary,
                evaluator_executed=True,
                evaluator_exit_code=0,
            )

            altered_bound = copy.deepcopy(bound)
            altered_bound["rehash_extra"] = True
            altered_bound["bound_summary_hash"] = gov.canonical_json_hash(
                altered_bound, "bound_summary_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "bound summary keys differ"
            ):
                gov.validate_bound_summary(
                    altered_bound,
                    job=job,
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_raw_summary=False,
                )

            altered_bound = copy.deepcopy(bound)
            altered_bound["evaluator_process"]["rehash_extra"] = True
            altered_bound["bound_summary_hash"] = gov.canonical_json_hash(
                altered_bound, "bound_summary_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "evaluator process keys differ"
            ):
                gov.validate_bound_summary(
                    altered_bound,
                    job=job,
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_raw_summary=False,
                )

            altered_bound = copy.deepcopy(bound)
            altered_bound["g0_summary"]["support"]["rehash_extra"] = 0
            altered_bound["bound_summary_hash"] = gov.canonical_json_hash(
                altered_bound, "bound_summary_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "scientific support keys differ"
            ):
                gov.validate_bound_summary(
                    altered_bound,
                    job=job,
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_raw_summary=False,
                )

    def test_g0_lock_rejects_rehashed_evaluator_role_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            evil = root / "scripts/evil_evaluator.py"
            evil.parent.mkdir(parents=True, exist_ok=True)
            evil.write_text("# synthetic unauthorized evaluator\n", encoding="utf-8")
            altered = copy.deepcopy(lock)
            evaluator_record = next(
                record
                for record in altered["code_bindings"]
                if record["role"] == "evaluator"
            )
            evaluator_record.update(gov.file_record(root, evil))
            evaluator_record["role"] = "evaluator"
            altered["evaluation_lock_hash"] = gov.canonical_json_hash(
                altered, "evaluation_lock_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "code binding path differs"
            ):
                gov.validate_lock_payload(altered, root=root, verify_files=True)

    def test_g0_lock_rejects_rehashed_formalization_adoption_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            for mutation in ("path", "self_hash"):
                altered = copy.deepcopy(lock)
                if mutation == "path":
                    altered["formalization_adoption"]["path"] = (
                        "papers/ieee_sensors_journal_experiments/p07/evil.json"
                    )
                else:
                    altered["formalization_adoption"][
                        adoption.SELF_HASH_FIELD
                    ] = "f" * 64
                altered["evaluation_lock_hash"] = gov.canonical_json_hash(
                    altered, "evaluation_lock_hash"
                )
                with self.subTest(mutation=mutation):
                    with self.assertRaisesRegex(
                        gov.G0GovernanceError, "formalization-adoption"
                    ):
                        gov.validate_lock_payload(
                            altered, root=root, verify_files=True
                        )

    def test_g0_lock_rejects_rehashed_review_evidence_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            for mutation in ("path", "self_hash"):
                altered = copy.deepcopy(lock)
                if mutation == "path":
                    altered["formalization_review_evidence"]["path"] = (
                        "papers/ieee_sensors_journal_experiments/p07/evil.json"
                    )
                else:
                    altered["formalization_review_evidence"][
                        review_evidence.SELF_HASH_FIELD
                    ] = "f" * 64
                altered["evaluation_lock_hash"] = gov.canonical_json_hash(
                    altered, "evaluation_lock_hash"
                )
                with self.subTest(mutation=mutation):
                    with self.assertRaisesRegex(
                        gov.G0GovernanceError, "review-evidence"
                    ):
                        gov.validate_lock_payload(
                            altered, root=root, verify_files=True
                        )

    def test_g0_lock_rejects_rehashed_frozen_input_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            queue_record = next(
                record
                for record in lock["frozen_inputs"]
                if record["role"] == "backend_queue"
            )
            canonical = root / str(queue_record["path"])
            alternate = root / "alternate/backend_replay_queue_v1.csv"
            alternate.parent.mkdir(parents=True)
            alternate.write_bytes(canonical.read_bytes())
            altered = copy.deepcopy(lock)
            altered_record = next(
                record
                for record in altered["frozen_inputs"]
                if record["role"] == "backend_queue"
            )
            altered_record.update(gov.file_record(root, alternate))
            altered_record["role"] = "backend_queue"
            altered["evaluation_lock_hash"] = gov.canonical_json_hash(
                altered, "evaluation_lock_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "frozen input path differs"
            ):
                gov.validate_lock_payload(altered, root=root, verify_files=True)

    def test_rehashed_nested_reference_queue_and_epoch_semantics_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, _queue_path = self._build_authority(root)
            frozen = {
                record["role"]: record for record in lock["frozen_inputs"]
            }

            reference_path = root / str(frozen["reference_contracts"]["path"])
            reference_payload = json.loads(reference_path.read_text(encoding="utf-8"))
            altered_reference = copy.deepcopy(reference_payload)
            first = altered_reference["contracts"][0]
            first["reference_contract"]["max_reference_gap_s"] = 9.0
            record_core = dict(first)
            record_core.pop("reference_contract_hash")
            first["reference_contract_hash"] = gov.canonical_json_hash(record_core)
            altered_reference["reference_contracts_hash"] = gov.canonical_json_hash(
                altered_reference, "reference_contracts_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "audit-derived numeric fields differ"
            ):
                references.validate_reference_contracts(
                    altered_reference, root=root, verify_artifacts=True
                )

            queue_lock_path = root / str(frozen["backend_queue_lock"]["path"])
            original_queue_lock = json.loads(queue_lock_path.read_text(encoding="utf-8"))
            altered_queue_lock = copy.deepcopy(original_queue_lock)
            altered_queue_lock["source_evidence"][0]["source_provenance"][
                "kind"
            ] = "REHASHED_UNAUTHORIZED_SOURCE"
            altered_queue_lock["backend_queue_lock_hash"] = queue_builder.lock_hash(
                altered_queue_lock
            )
            write_json(queue_lock_path, altered_queue_lock)
            altered_lock = copy.deepcopy(lock)
            altered_queue_record = next(
                record
                for record in altered_lock["frozen_inputs"]
                if record["role"] == "backend_queue_lock"
            )
            altered_queue_record.update(gov.file_record(root, queue_lock_path))
            altered_queue_record["role"] = "backend_queue_lock"
            altered_lock["backend_bindings"]["queue_lock_self_hash"] = (
                altered_queue_lock["backend_queue_lock_hash"]
            )
            altered_lock["evaluation_lock_hash"] = gov.canonical_json_hash(
                altered_lock, "evaluation_lock_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "source provenance hash drift|source evidence"
            ):
                gov.validate_lock_payload(
                    altered_lock, root=root, verify_files=True
                )

            write_json(queue_lock_path, original_queue_lock)
            epoch_path = root / str(
                frozen["evaluator_epoch_ns_correction_lock"]["path"]
            )
            epoch_payload = json.loads(epoch_path.read_text(encoding="utf-8"))
            epoch_payload["epoch_ns_correction"]["new_ros_bag_conversion"] = (
                "float(stamp.to_sec())"
            )
            epoch_payload["epoch_ns_correction_lock_hash"] = (
                epoch_builder.canonical_json_hash(
                    epoch_payload, "epoch_ns_correction_lock_hash"
                )
            )
            write_json(epoch_path, epoch_payload)
            altered_lock = copy.deepcopy(lock)
            altered_epoch_record = next(
                record
                for record in altered_lock["frozen_inputs"]
                if record["role"] == "evaluator_epoch_ns_correction_lock"
            )
            altered_epoch_record.update(gov.file_record(root, epoch_path))
            altered_epoch_record["role"] = "evaluator_epoch_ns_correction_lock"
            altered_lock["backend_bindings"]["epoch_ns_correction_self_hash"] = (
                epoch_payload["epoch_ns_correction_lock_hash"]
            )
            altered_lock["evaluation_lock_hash"] = gov.canonical_json_hash(
                altered_lock, "evaluation_lock_hash"
            )
            with self.assertRaisesRegex(
                (ValueError, gov.G0GovernanceError),
                "semantic literals differ|invalid nested epoch",
            ):
                gov.validate_lock_payload(
                    altered_lock, root=root, verify_files=True
                )

    def test_k0_materializes_180_and_full_reducer_consumes_exact_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, plan, jobs, _queue_path = self._build_authority(
                root, hard_first=True
            )
            self.assertEqual(
                {record["role"] for record in lock["frozen_inputs"]},
                set(gov.REQUIRED_FROZEN_INPUT_ROLES),
            )
            self.assertNotIn(
                "backend_execution_lock",
                {record["role"] for record in lock["frozen_inputs"]},
            )
            self.assertEqual(len(jobs), 180)
            self.assertEqual(
                sum(
                    job["evaluation_job"]["route"]
                    == evaluation.ROUTE_B0_DESCRIPTIVE
                    for job in jobs
                ),
                60,
            )
            staging = (root / "jobs").with_name(
                f".jobs.staging-{plan['plan_basis_hash'][:16]}"
            )
            staging.mkdir()
            first_job = jobs[0]
            write_json(
                staging / materializer._safe_job_filename(str(first_job["job_id"])),
                first_job,
            )
            plan_path = materializer.publish_plan_bundle(
                plan, jobs, root=root, job_root=root / "jobs"
            )
            self.assertTrue(plan_path.is_file())
            self.assertEqual(
                materializer.publish_plan_bundle(
                    plan, jobs, root=root, job_root=root / "jobs"
                ),
                plan_path,
            )
            first_membership = plan["jobs"][0]
            evaluator_record = next(
                record
                for record in lock["code_bindings"]
                if record["role"] == "evaluator"
            )
            validated_job, validated_plan, validated_lock = (
                runner.validate_production_inputs(
                    gov.workspace_path(
                        root, first_membership["path"], label="first G0 job"
                    ),
                    plan_path,
                    root / "g0_evaluation_lock_v1.json",
                    root=root,
                    evaluator_script=gov.workspace_path(
                        root, evaluator_record["path"], label="fixture evaluator"
                    ),
                    evaluator_protocol=root / "evaluator_protocol_v1.md",
                )
            )
            self.assertEqual(validated_job["job_id"], first_membership["job_id"])
            self.assertEqual(validated_plan["plan_hash"], plan["plan_hash"])
            self.assertEqual(
                validated_lock["evaluation_lock_hash"],
                lock["evaluation_lock_hash"],
            )
            numeric_job = next(
                job
                for job in jobs
                if job["evaluation_job"]["evaluation_disposition"]
                == "EVALUATE_NUMERIC"
            )
            numeric_core = numeric_job["evaluation_job"]
            command = runner.build_g0_command(
                numeric_core,
                evaluator_script=str(
                    gov.workspace_path(
                        root, evaluator_record["path"], label="fixture evaluator"
                    )
                ),
                output_dir_override=str(
                    Path(str(numeric_job["output_dir_absolute"])).with_name(
                        ".fixture-staging"
                    )
                ),
            )
            reference_contract = numeric_core["reference"]
            self.assertEqual(
                command[command.index("--window-start-s") + 1],
                references.ns_to_decimal_seconds(
                    reference_contract["window_start_ns"]
                ),
            )
            self.assertEqual(
                command[command.index("--window-end-s") + 1],
                references.ns_to_decimal_seconds(reference_contract["window_end_ns"]),
            )
            overrides = {str(reference_contract["path"]): "/proc/self/fd/501"}
            for index, arm in enumerate(numeric_core["arms"].values(), 502):
                overrides[str(arm["trajectory_path"])] = f"/proc/self/fd/{index}"
                overrides[str(arm["config_path"])] = f"/proc/self/fd/{index + 100}"
            secured = runner.build_g0_command(
                numeric_core,
                evaluator_script="/proc/self/fd/500",
                output_dir_override="/proc/self/fd/599",
                input_path_overrides=overrides,
            )
            self.assertEqual(
                secured[:3], ["python3", "-I", "/proc/self/fd/500"]
            )
            self.assertIn("/proc/self/fd/501", secured)
            self.assertNotIn(str(reference_contract["path"]), secured)
            self.assertTrue(
                all(
                    value.split("=", 1)[-1].startswith("/proc/self/fd/")
                    for index, value in enumerate(secured)
                    if secured[index - 1] in {"--arm", "--arm-config"}
                )
            )
            validated_plan_context: dict[str, object] = {}
            gov.validate_plan_payload(
                plan,
                lock=lock,
                root=root,
                _context_out=validated_plan_context,
            )
            forged_plan_context = dict(validated_plan_context)
            forged_plan_context["_validation_token"] = object()
            with self.assertRaisesRegex(
                gov.G0GovernanceError, "validated G0 plan context differs"
            ):
                gov.validate_job_payload(
                    jobs[0],
                    plan=plan,
                    lock=lock,
                    root=root,
                    verify_inputs=False,
                    _validated_plan_context=forged_plan_context,
                )

            # The optimized per-job loop intentionally performs no file I/O;
            # the full post-loop plan validation is therefore the mutation
            # fence.  Prove that even an otherwise parseable source change is
            # rejected before a materialized bundle can be returned.
            fenced_terminal_record = self._last_terminal_index["bindings"][0]
            fenced_terminal_path = root / str(fenced_terminal_record["path"])
            fenced_terminal_bytes = fenced_terminal_path.read_bytes()
            fenced_terminal_path.write_bytes(fenced_terminal_bytes + b"\n")
            try:
                with self.assertRaises(gov.G0GovernanceError):
                    gov.validate_plan_payload(plan, lock=lock, root=root)
            finally:
                fenced_terminal_path.write_bytes(fenced_terminal_bytes)

            validation_call_guard = ExitStack()
            self.addCleanup(validation_call_guard.close)
            repeated_plan_validation = validation_call_guard.enter_context(
                mock.patch.object(
                    gov, "validate_plan_payload", wraps=gov.validate_plan_payload
                )
            )
            repeated_lock_validation = validation_call_guard.enter_context(
                mock.patch.object(
                    gov, "validate_lock_payload", wraps=gov.validate_lock_payload
                )
            )
            repeated_execution_authority_validation = (
                validation_call_guard.enter_context(
                    mock.patch.object(
                        gov,
                        "validate_execution_authority_binding",
                        wraps=gov.validate_execution_authority_binding,
                    )
                )
            )
            for job in jobs:
                core = job["evaluation_job"]
                assert isinstance(core, dict)
                intent = publisher.build_publication_intent(
                    root=root,
                    job_id=str(job["job_id"]),
                    job_hash=str(job["job_hash"]),
                    plan_hash=str(plan["plan_hash"]),
                    evaluation_lock_hash=str(lock["evaluation_lock_hash"]),
                    backend_execution_lock_hash=str(
                        job["backend_execution_lock_hash"]
                    ),
                    g0_execution_authority_hash=str(
                        job["g0_execution_authority_hash"]
                    ),
                    evaluation_disposition=str(core["evaluation_disposition"]),
                    output_dir=Path(str(job["output_dir_absolute"])),
                )
                intent_path = Path(str(intent["intent_path_absolute"]))
                staging = Path(str(intent["staging_absolute"]))
                publisher.create_publication_intent(intent_path, intent, root=root)
                staging.mkdir()
                numeric = core["evaluation_disposition"] == "EVALUATE_NUMERIC"
                summary = self._numeric_summary(core) if numeric else None
                if summary is not None:
                    write_json(staging / "common_support_summary.json", summary)
                bound = runner.build_bound_summary(
                    job,
                    plan,
                    lock,
                    root=root,
                    staging=staging,
                    numeric_summary=summary,
                    evaluator_executed=numeric,
                    evaluator_exit_code=0 if numeric else None,
                    validated_plan_context=validated_plan_context,
                )
                write_json(staging / publisher.BOUND_SUMMARY_NAME, bound)
                publisher.seal_staging_result(intent, root=root)
                publisher.publish_staging(
                    intent,
                    root=root,
                    closeout_path=Path(str(intent["closeout_path_absolute"])),
                )
            validation_call_guard.close()
            self.assertEqual(repeated_plan_validation.call_count, 0)
            self.assertEqual(repeated_lock_validation.call_count, 0)
            self.assertEqual(
                repeated_execution_authority_validation.call_count, 0
            )
            reducer_probe_job = jobs[0]
            reducer_probe_summary = (
                Path(str(reducer_probe_job["output_dir_absolute"]))
                / publisher.BOUND_SUMMARY_NAME
            )
            reducer_probe_original = reducer_probe_summary.read_bytes()
            reducer_probe_stat = reducer_probe_summary.stat()
            original_inventory = publisher._inventory_open_result
            inventory_calls = 0

            def mutate_restore_after_snapshot(
                descriptor: int, *, durable: bool
            ):
                nonlocal inventory_calls
                observed = original_inventory(descriptor, durable=durable)
                inventory_calls += 1
                # validate_closeout performs the first two inventories.  The
                # retained reducer context performs inventories three/four
                # and yields only after the fourth; mutate+restore at that
                # exact read window so its final fifth inventory must reject.
                if inventory_calls == 4:
                    reducer_probe_summary.write_bytes(b'{"attacker": true}\n')
                    reducer_probe_summary.write_bytes(reducer_probe_original)
                    os.utime(
                        reducer_probe_summary,
                        ns=(
                            reducer_probe_stat.st_atime_ns,
                            reducer_probe_stat.st_mtime_ns,
                        ),
                    )
                return observed

            with mock.patch.object(
                publisher,
                "_inventory_open_result",
                side_effect=mutate_restore_after_snapshot,
            ):
                with self.assertRaisesRegex(
                    gov.G0GovernanceError,
                    "changed during retained snapshot use",
                ):
                    reducer._load_result(
                        reducer_probe_job,
                        plan,
                        lock,
                        root=root,
                        plan_context=validated_plan_context,
                    )
            reduced = reducer.build_full_reduction(plan, lock, root=root)
            validated_reduction_hash = reducer.validate_full_reduction(
                reduced, plan=plan, lock=lock, root=root
            )
            reduction_mutations = (
                lambda value: value.__setitem__("extra", True),
                lambda value: value["reduction_policy"].__setitem__(
                    "minimum_evaluable_replays", 1
                ),
                lambda value: value["receipt_bindings"][0]["receipt"].__setitem__(
                    "sha256", "0" * 64
                ),
                lambda value: value["window_arm_reductions"][0].__setitem__(
                    "reduction_status", "TAMPERED"
                ),
                lambda value: value["pairwise_contrasts"][0].__setitem__(
                    "contrast_name", "TAMPERED"
                ),
            )
            for mutate in reduction_mutations:
                altered = copy.deepcopy(reduced)
                mutate(altered)
                altered["full_reduction_hash"] = gov.canonical_json_hash(
                    altered, "full_reduction_hash"
                )
                with mock.patch.object(
                    reducer, "build_full_reduction", return_value=reduced
                ):
                    with self.assertRaises(gov.G0GovernanceError):
                        reducer.validate_full_reduction(
                            altered, plan=plan, lock=lock, root=root
                        )
        self.assertEqual(
            reduced["counts"],
            {
                "jobs": 180,
                "receipts": 180,
                "window_arm_reductions": 100,
                "pairwise_contrasts": 40,
                "applicable_d_windows": 0,
            },
        )
        b0_hard = [
            item
            for item in reduced["window_arm_reductions"]
            if item["arm"] == evaluation.ARM_B0
            and item["hard_failure_any_of_three"] is True
        ]
        self.assertEqual(len(b0_hard), 1)
        self.assertEqual(b0_hard[0]["reduction_status"], "NUMERIC_2_OF_3")
        self.assertEqual(
            validated_reduction_hash,
            reduced["full_reduction_hash"],
        )

    def test_collector_binds_lock_source_provenance_and_reconciles_exact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, _plan, _jobs, queue_path = self._build_authority(root)
            lock_path = root / "g0_evaluation_lock_v1.json"
            execution_lock_path = root / "backend_replay_execution_lock_v1.json"
            _fields, rows = gov.read_csv(queue_path)
            row = rows[0]
            run_dir = root / row["expected_run_dir"]
            trajectory = run_dir / "vins_output/vio.csv"
            config = root / "artifacts/config.yaml"
            log = run_dir / "vins.log"
            manifest = run_dir / "backend_replay_manifest.txt"
            log.write_text("normal terminal log\n", encoding="utf-8")
            manifest.write_text(
                "schema_version=isj-p07-backend-replay-manifest-v1\n"
                f"vins_config={config}\n",
                encoding="utf-8",
            )
            audit: dict[str, object] = {
                "schema_version": collector.AUDIT_SCHEMA,
                "status": "PASS",
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": int(row["replay_index"]),
                "terminal": True,
                "terminal_process_status": "PASS_EXECUTION_ENVELOPE",
                "replay_hard_failure": False,
                "numeric_evaluation_candidate": True,
                "g0_evaluation_pending": True,
                "failure_code": None,
                "run_dir": gov.display_path(root, run_dir),
                "checks": {
                    "job_only_governed_adapter": True,
                    "job_authority_manifest_valid": True,
                    "data_identity_manifest_link_target_revalidated": True,
                    "durable_attempt_intent_and_state_chain_valid": True,
                    "expected_run_no_clobber": True,
                    "trajectory_values_read": False,
                    "ape_rpe_values_read": False,
                },
                "outcome_boundary": (
                    "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
                ),
                "output_structure": {
                    name: {
                        "path": os.fspath(path),
                        "exists": path.is_file(),
                        "size_bytes": (
                            path.stat().st_size if path.is_file() else None
                        ),
                    }
                    for name, path in {
                        "vins_log": log,
                        "vins_environment": run_dir / "vins_env_manifest.txt",
                        "trajectory": trajectory,
                        "backend_replay_manifest": manifest,
                        "preparation_manifest": run_dir / "replay_manifest.txt",
                        "ape_report": run_dir / "ape.txt",
                        "rpe_report": run_dir / "rpe.txt",
                        "ape_rpe_report": run_dir / "ape_rpe.json",
                    }.items()
                },
            }
            audit_path = root / row["expected_attempt_dir"] / "audit_v1.json"
            write_json(audit_path, audit)
            audit_record = gov.file_record(root, audit_path)
            output_manifest_path = (
                root / row["expected_attempt_dir"] / "output_hash_manifest.sha256"
            )
            output_manifest_path.write_text(
                f"{audit_record['sha256']}  {audit_record['path']}\n",
                encoding="utf-8",
            )
            output_manifest_hash = gov.sha256_file(output_manifest_path)
            registry_path = root / lock["mutable_registry_prefix"]["path"]
            with registry_path.open(newline="", encoding="utf-8") as handle:
                registry_fields = list((reader := csv.DictReader(handle)).fieldnames or [])
                registry_rows = list(reader)
            terminal_registry = next(
                item
                for item in registry_rows
                if item["run_id"] == row["run_id"] and item["status"] == "COMPLETED"
            )
            terminal_registry["notes"] = (
                f"audit={audit_record['path']}; "
                f"audit_sha256={audit_record['sha256']}; "
                f"output_manifest_sha256={output_manifest_hash}"
            )
            with registry_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=registry_fields)
                writer.writeheader()
                writer.writerows(registry_rows)
            reference_path = next(
                gov.workspace_path(root, record["path"], label="reference contracts")
                for record in lock["frozen_inputs"]
                if record["role"] == "reference_contracts"
            )
            failure, classification, terminal = collector.canonical_collection_paths(
                root, row
            )
            # _build_authority materializes one canonical terminal to exercise
            # downstream plan validation.  This test starts immediately before
            # the collector's three-file commit, so remove only that synthetic
            # prebuilt terminal; failure/classification are not yet canonical.
            if terminal.is_file():
                terminal.unlink()
            first = collector.publish_collection(
                row,
                root=root,
                queue_path=queue_path,
                evaluation_lock_path=lock_path,
                execution_lock_path=execution_lock_path,
                audit_path=audit_path,
                reference_contracts_path=reference_path,
                failure_output=failure,
                classification_output=classification,
                binding_output=terminal,
                strict_execution_lock_validation=False,
            )
            second = collector.publish_collection(
                row,
                root=root,
                queue_path=queue_path,
                evaluation_lock_path=lock_path,
                execution_lock_path=execution_lock_path,
                audit_path=audit_path,
                reference_contracts_path=reference_path,
                failure_output=failure,
                classification_output=classification,
                binding_output=terminal,
                strict_execution_lock_validation=False,
            )
        self.assertEqual(first, second)
        binding = first[-1]
        self.assertEqual(binding["source_run_id"], row["source_run_id"])
        self.assertEqual(
            binding["source_provenance_hash"], row["source_provenance_hash"]
        )
        self.assertEqual(
            binding["backend_algorithmic_slot"], row["algorithmic_slot"]
        )
        self.assertEqual(
            first[0]["queue"]["evidence_status"],
            "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
        )

    def test_job_with_rehashed_outside_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock, plan, jobs, _queue_path = self._build_authority(root)
            job = copy.deepcopy(jobs[0])
            mutated_plan = copy.deepcopy(plan)
            job["output_dir_absolute"] = "/tmp/escaped-g0-output"
            job["job_hash"] = gov.canonical_json_hash(job, "job_hash")
            membership = next(
                item
                for item in mutated_plan["jobs"]
                if item["job_id"] == job["job_id"]
            )
            membership["job_hash"] = job["job_hash"]
            membership["output_dir_absolute"] = job["output_dir_absolute"]
            mutated_plan["plan_hash"] = gov.canonical_json_hash(
                mutated_plan, "plan_hash"
            )
            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "deterministic G0 plan membership identity mismatch",
            ):
                gov.validate_job_payload(
                    job,
                    plan=mutated_plan,
                    lock=lock,
                    root=root,
                    verify_inputs=False,
                )


if __name__ == "__main__":
    unittest.main()
