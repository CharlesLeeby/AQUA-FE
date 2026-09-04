from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from scripts import build_p07_preoutcome_governance_v1 as governance
from scripts import build_p07_q58_orphan_closeout_lock_v1 as contract
from scripts import closeout_p07_q58_orphan_execution_v1 as closeout


RUN_ID = (
    "isj-nativeq-v3_P07_aqualoc_archaeology-A07_900-1800_"
    "M_f0_b00_20260806T084500Z"
)


def registry_event(number: int, status: str) -> dict[str, str]:
    return {
        "run_id": RUN_ID,
        "registry_event_id": f"{RUN_ID}_e{number:02d}",
        "supersedes_event_id": "" if number == 0 else f"{RUN_ID}_e{number - 1:02d}",
        "status": status,
        "command_file": (
            contract.auditor.display_path(contract.ATTEMPT / "command.txt")
            if number
            else contract.auditor.display_path(governance.EXPORT_QUEUE)
        ),
        "input_hash_manifest": (
            contract.auditor.display_path(
                contract.ATTEMPT / "input_hash_manifest.sha256"
            )
            if number
            else "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt"
        ),
        "output_hash_manifest": "",
        "run_dir": (
            "logs/aqualoc_archaeo_vins"
            if number == 1
            else contract.auditor.display_path(contract.RUN_DIR)
        ),
        "infrastructure_failure": "" if number < 2 else "false",
        "notes": (
            "generalized v3 no-clobber executor started queue_index=58; "
            "guard-only preflight exact PASS; predecessor queue_index=55 satisfied "
            "by additive replacement; canonical q55 remains FAILED"
            if number == 1
            else ""
        ),
    }


def valid_audit(attestation: Path) -> dict[str, object]:
    return {
        "schema_version": "isj-p07-frontend-export-audit-v4",
        "status": "PASS",
        "queue_index": contract.QUEUE_INDEX,
        "run_id": RUN_ID,
        "arm": governance.M_ARM,
        "run_dir": contract.auditor.display_path(contract.RUN_DIR),
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "held_out_trajectory_outcome_read": False,
        "checks": {
            "no_trajectory_outcome_artifacts": True,
            "arm_attestation_bound": True,
        },
        "feature_bag": {
            "path": contract.auditor.display_path(contract.FEATURE_BAG),
            "sha256": "a" * 64,
            "feature_frames": 450,
            "feature_observations": 12345,
        },
        "attestation": {"path": contract.auditor.display_path(attestation)},
        "forbidden_outcome_artifacts": [],
    }


class Q58OrphanCloseoutContractTests(unittest.TestCase):
    def test_post_child_transitive_attester_dependencies_are_bound(self) -> None:
        names = {path.name for path in contract.TRANSITIVE_POST_CHILD_FILES}
        self.assertIn("attest_p05_xfeat_feature_bag_v1.py", names)
        self.assertIn("build_nativeq_backend_contract.py", names)
        self.assertIn("check_nativeq_backend_contract.py", names)
        self.assertIn("check_p05_xfeat_backend_contract_v1.py", names)
        self.assertIn("audit_p07_frontend_export_v4.py", names)
        self.assertIn("run_p07_q55_a04_layout_replacement_v1.py", names)
        self.assertIn("build_p07_q55_a04_layout_replacement_lock_v1.py", names)
        self.assertIn("reclaim_p07_raw_cache_v1.py", names)
        self.assertIn("resolve_p07_d_applicability_v4.py", names)
        self.assertIn("run_p07_frontend_queue_v6.py", names)

    def test_builder_publication_holds_shared_correction_action_lock(self) -> None:
        order: list[str] = []

        @contextmanager
        def action_lock():
            order.append("lock-enter")
            try:
                yield
            finally:
                order.append("lock-exit")

        payload = {"closeout_lock_hash": "a" * 64}
        with mock.patch.object(
            contract.correction_runtime, "action_lock", side_effect=action_lock
        ), mock.patch.object(
            contract, "build_lock", side_effect=lambda: order.append("build") or payload
        ), mock.patch.object(
            contract,
            "atomic_write_json_no_clobber",
            side_effect=lambda *_args: order.append("publish"),
        ), mock.patch("builtins.print"):
            self.assertEqual(contract.main(), 0)
        self.assertEqual(order, ["lock-enter", "build", "publish", "lock-exit"])

    def test_active_q58_process_blocks_lock_build(self) -> None:
        active = [{"pid": 49141, "cmdline": ["bash", str(contract.FEATURE_BAG)]}]
        with mock.patch.object(contract, "assert_postprocess_absent"), mock.patch.object(
            contract, "active_q58_processes", return_value=active
        ):
            with self.assertRaisesRegex(
                contract.OrphanCloseoutViolation, "physical process is still active"
            ):
                contract.build_lock()

    def test_proc_scanner_matches_exact_runner_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            process = proc / "49141"
            process.mkdir()
            (process / "cmdline").write_bytes(
                b"\0".join(
                    (
                        b"bash",
                        b"/home/ma/AQUA-FE_WS/scripts/run_aqualoc_archaeo_vins_eval.sh",
                        b"external",
                        b"7",
                        b"900",
                        b"1800",
                        b"xfeat",
                        b"2",
                    )
                )
                + b"\0"
            )
            active = contract.active_q58_processes(proc, own_pid=99999)
        self.assertEqual([item["pid"] for item in active], [49141])

    def test_non_running_or_extended_registry_chain_is_rejected(self) -> None:
        bad_status = [registry_event(0, "PLANNED"), registry_event(1, "FAILED")]
        with self.assertRaisesRegex(contract.OrphanCloseoutViolation, "event mismatch"):
            contract.validate_registry_chain(bad_status, RUN_ID)
        extended = [
            registry_event(0, "PLANNED"),
            registry_event(1, "RUNNING"),
            registry_event(2, "COMPLETED"),
        ]
        with self.assertRaisesRegex(contract.OrphanCloseoutViolation, "not exact e00/e01"):
            contract.validate_registry_chain(extended, RUN_ID)

    def test_atomic_lock_write_refuses_complete_and_partial_collisions(self) -> None:
        payload = {"schema_version": "fixture"}
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "lock.json"
            target.write_text("preserve", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                contract.atomic_write_json_no_clobber(target, payload)
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve")
            target.unlink()
            partial = target.with_name(f"{target.name}.partial.123")
            partial.write_text("preserve-partial", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                contract.atomic_write_json_no_clobber(target, payload)
            self.assertFalse(target.exists())
            self.assertEqual(partial.read_text(encoding="utf-8"), "preserve-partial")

    def test_closeout_refuses_partial_postprocess_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "audit_v4.json"
            partial = target.with_name(f"{target.name}.partial.777")
            partial.write_text("partial", encoding="utf-8")
            with mock.patch.object(contract, "postprocess_paths", return_value=(target,)):
                with self.assertRaisesRegex(FileExistsError, "partial/no-clobber"):
                    closeout.assert_closeout_outputs_absent()

    def test_closeout_transaction_holds_shared_correction_action_lock(self) -> None:
        order: list[str] = []

        @contextmanager
        def action_lock():
            order.append("lock-enter")
            try:
                yield
            finally:
                order.append("lock-exit")

        report = {"completion_registry_event_id": f"{RUN_ID}_e02", "feature_frames": 450}
        with mock.patch.object(
            contract.correction_runtime, "action_lock", side_effect=action_lock
        ), mock.patch.object(
            closeout,
            "perform_locked_closeout",
            side_effect=lambda: order.append("closeout") or report,
        ), mock.patch("builtins.print"):
            self.assertEqual(closeout.main(), 0)
        self.assertEqual(order, ["lock-enter", "closeout", "lock-exit"])

    def test_postprocess_revalidation_blocks_reactivated_q58(self) -> None:
        with mock.patch.object(
            contract,
            "active_q58_processes",
            return_value=[{"pid": 51928, "cmdline": [str(contract.FEATURE_BAG)]}],
        ):
            with self.assertRaisesRegex(
                closeout.OrphanExecutionCloseoutViolation,
                "process active after postprocess",
            ):
                closeout.revalidate_after_postprocess(
                    {}, {"command": "RUN_VINS=0 fixture"}, {"run_id": RUN_ID}
                )

    def test_revalidation_precedes_manifest_and_e02_publication(self) -> None:
        order: list[str] = []
        row = {"arm": governance.M_ARM}
        allocation = {"run_id": RUN_ID}
        lock = {"closeout_lock_hash": "c" * 64}
        audit = valid_audit(contract.ATTESTATION)
        event = registry_event(2, "COMPLETED")
        report = {"status": closeout.STATUS}
        with mock.patch.object(closeout, "assert_closeout_outputs_absent"), mock.patch.object(
            closeout, "load_and_validate_lock", return_value=(lock, row, allocation)
        ), mock.patch.object(
            closeout,
            "run_locked_postprocess",
            side_effect=lambda *_args: order.append("postprocess")
            or (
                contract.RUN_DIR,
                contract.ATTESTATION,
                audit,
                Path("/tmp/actual-guard"),
                Path("/tmp/preflight-guard"),
            ),
        ), mock.patch.object(
            closeout,
            "revalidate_after_postprocess",
            side_effect=lambda *_args: order.append("revalidate"),
        ), mock.patch.object(
            closeout.base, "output_files", return_value=[]
        ), mock.patch.object(
            closeout,
            "publish_output_manifest_no_clobber",
            side_effect=lambda *_args: order.append("manifest")
            or contract.OUTPUT_MANIFEST,
        ), mock.patch.object(
            closeout,
            "append_completion_event",
            side_effect=lambda **_kwargs: order.append("e02") or event,
        ), mock.patch.object(
            closeout, "build_closeout_report", return_value=report
        ), mock.patch.object(
            contract, "atomic_write_json_no_clobber"
        ):
            self.assertIs(closeout.perform_locked_closeout(), report)
        self.assertEqual(order, ["postprocess", "revalidate", "manifest", "e02"])

    def test_postprocess_uses_v5_adapter_and_requires_exact_v4_audit(self) -> None:
        row = {"arm": governance.M_ARM}
        allocation = {"run_id": RUN_ID}
        attestation = contract.ATTESTATION
        audit = valid_audit(attestation)
        actual_guard = Path("/tmp/q58-actual-guard.json")
        preflight_guard = Path("/tmp/q58-preflight-guard.json")
        with mock.patch.object(
            closeout.auditor,
            "resolve_run_artifacts",
            return_value=(
                contract.auditor.lexical_absolute(contract.RUN_DIR),
                contract.auditor.lexical_absolute(contract.FEATURE_BAG),
                None,
                None,
                {},
            ),
        ), mock.patch.object(
            closeout.auditor,
            "parse_guard_path",
            side_effect=[actual_guard, preflight_guard],
        ), mock.patch.object(
            closeout.auditor, "validate_guard", return_value={}
        ), mock.patch.object(
            closeout.v5, "install_corrected_contract"
        ) as install, mock.patch.object(
            closeout.base,
            "run_attestation",
            return_value=(attestation, contract.ATTESTATION_LOG),
        ) as attest, mock.patch.object(
            closeout.base,
            "run_audit",
            return_value=(contract.AUDIT, contract.AUDIT_LOG, audit),
        ) as run_audit:
            result = closeout.run_locked_postprocess(row, allocation)
        install.assert_called_once_with()
        attest.assert_called_once()
        run_audit.assert_called_once_with(
            contract.QUEUE_INDEX,
            contract.ATTEMPT / "command.log",
            attestation,
            contract.ATTEMPT,
        )
        self.assertEqual(result[2]["schema_version"], "isj-p07-frontend-export-audit-v4")

    def test_invalid_audit_adapter_is_rejected(self) -> None:
        audit = valid_audit(contract.ATTESTATION)
        audit["schema_version"] = "isj-p07-frontend-export-audit-v3"
        with self.assertRaisesRegex(
            closeout.OrphanExecutionCloseoutViolation, "audit identity mismatch"
        ):
            closeout.validate_audit(
                audit,
                allocation={"run_id": RUN_ID},
                attestation=contract.ATTESTATION,
            )

    def test_completion_is_direct_running_to_completed_e02(self) -> None:
        allocation = {"run_id": RUN_ID}
        event = registry_event(2, "COMPLETED")
        event.update(
            {
                "run_dir": contract.auditor.display_path(contract.RUN_DIR),
                "output_hash_manifest": contract.auditor.display_path(
                    contract.OUTPUT_MANIFEST
                ),
                "infrastructure_failure": "false",
            }
        )
        with mock.patch.object(
            closeout.base, "append_registry_event", return_value=event
        ) as append:
            observed = closeout.append_completion_event(
                allocation=allocation,
                run_dir=contract.RUN_DIR,
                output_manifest=contract.OUTPUT_MANIFEST,
                audit_path=contract.AUDIT,
            )
        _args, kwargs = append.call_args
        self.assertEqual(kwargs["expected_previous_status"], "RUNNING")
        self.assertEqual(kwargs["status"], "COMPLETED")
        self.assertEqual(kwargs["infrastructure_failure"], "false")
        self.assertEqual(observed["registry_event_id"], f"{RUN_ID}_e02")
        self.assertNotIn("FAILED", kwargs["note"])

    def test_closeout_report_preserves_no_rerun_and_trajectory_boundary(self) -> None:
        event = registry_event(2, "COMPLETED")
        event.update(
            {
                "run_dir": contract.auditor.display_path(contract.RUN_DIR),
                "output_hash_manifest": contract.auditor.display_path(
                    contract.OUTPUT_MANIFEST
                ),
                "infrastructure_failure": "false",
            }
        )
        audit = valid_audit(contract.ATTESTATION)
        fake_record = {"path": "fixture", "sha256": "b" * 64, "size_bytes": 1}
        with mock.patch.object(contract, "file_record", return_value=fake_record):
            report = closeout.build_closeout_report(
                lock={"closeout_lock_hash": "c" * 64},
                allocation={"run_id": RUN_ID},
                event=event,
                audit=audit,
            )
        self.assertIs(report["physical_frontend_rerun"], False)
        self.assertIs(report["trajectory_outcome_read"], False)
        self.assertIs(report["fabricated_failed_registry_event"], False)
        self.assertEqual(report["completion_registry_event_id"], f"{RUN_ID}_e02")
        self.assertEqual(
            report["closeout_hash"], contract.document_hash(report, "closeout_hash")
        )


if __name__ == "__main__":
    unittest.main()
