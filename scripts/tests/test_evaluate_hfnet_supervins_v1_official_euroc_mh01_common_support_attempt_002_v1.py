#!/usr/bin/env python3
"""Corrective control, lexer, and synthetic-render tests for Stage6 attempt_002."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/evaluate_hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_v1.py"
SPEC = importlib.util.spec_from_file_location("stage6_common_support_attempt_002", str(MODULE_PATH))
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def rotation_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.asarray([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def exact_synthetic_common() -> dict:
    t = np.linspace(-2.0, 3.0, M.BASE.COMMON_COUNT)
    gt = np.column_stack((t, 0.25 * t * t + 0.15 * np.sin(1.3 * t), np.sin(0.7 * t) + 0.04 * t * t * t))
    hf = (rotation_z(-0.31) @ (gt - np.asarray([1.1, -0.3, 0.5])).T).T
    sv = 1.08 * (rotation_z(0.43) @ (gt - np.asarray([-0.6, 1.2, -0.2])).T).T
    rows = []
    for index in range(M.BASE.COMMON_COUNT):
        camera_row = M.BASE.COMMON_FIRST + 2 * index
        timestamp_ns = M.BASE.COMMON_FIRST_NS + 100_000_000 * index
        rows.append({
            "common_row_index": index, "camera_row_index": camera_row,
            "source_timestamp_ns": timestamp_ns, "gt_row_index": 1000 + index,
            "gt_position": gt[index].tolist(), "hfnet_position": hf[index].tolist(),
            "supervins_position": sv[index].tolist(),
        })
    pairs = []
    for index in range(M.BASE.RPE_COUNT):
        pairs.append({
            "pair_row_index": index,
            "left_common_index": index, "right_common_index": index + M.BASE.RPE_INDEX_DELTA,
            "left_camera_row_index": rows[index]["camera_row_index"],
            "right_camera_row_index": rows[index + M.BASE.RPE_INDEX_DELTA]["camera_row_index"],
            "left_timestamp_ns": rows[index]["source_timestamp_ns"],
            "right_timestamp_ns": rows[index + M.BASE.RPE_INDEX_DELTA]["source_timestamp_ns"],
            "delta_ns": M.BASE.RPE_DELTA_NS,
            "left_association_index": index, "right_association_index": index + M.BASE.RPE_INDEX_DELTA,
        })
    return {"rows": rows, "pairs": pairs, "gt": gt, "hfnet": hf, "supervins": sv}


class WholeTokenLexerTests(unittest.TestCase):
    def test_generation_operation_restoration_are_allowed(self) -> None:
        audit = M.validate_report_boundary(["generation operation restoration"])
        self.assertTrue(audit["ok"], audit)
        self.assertFalse(audit["substring_matching_used"])

    def test_required_ratio_forms_are_rejected(self) -> None:
        for text in ("ratio", "metric_ratio", "cross-system ratio"):
            with self.subTest(text=text):
                audit = M.validate_report_boundary([text])
                self.assertFalse(audit["ok"])
                self.assertIn("ratio", audit["forbidden_tokens_found"])

    def test_inflections_and_phrases_are_rejected(self) -> None:
        text = "differences ratios outperformed superiority rankings percentage improvement p_values confidence intervals effect sizes"
        audit = M.validate_report_boundary([text])
        self.assertFalse(audit["ok"])
        for label in ("difference", "ratio", "outperform", "superior", "rank", "percent", "improvement", "p-value", "confidence interval", "effect size"):
            self.assertIn(label, audit["forbidden_tokens_found"])

    def test_p_value_separator_forms_are_rejected(self) -> None:
        for text in ("p-value", "p_value", "p value", "p values"):
            with self.subTest(text=text):
                self.assertIn("p-value", M.validate_report_boundary([text])["forbidden_tokens_found"])

    def test_every_frozen_lexeme_and_phrase_form_is_rejected(self) -> None:
        addendum = json.loads(M.ADDENDUM.read_text(encoding="utf-8"))
        for text in addendum["corrective_delta"]["forbidden_lexemes"] + addendum["corrective_delta"]["forbidden_phrases"]:
            with self.subTest(text=text):
                self.assertFalse(M.validate_report_boundary([text])["ok"])

    def test_percent_symbol_is_rejected(self) -> None:
        self.assertFalse(M.validate_report_boundary(["5%"])["ok"])

    def test_substrings_inside_longer_tokens_remain_allowed(self) -> None:
        audit = M.validate_report_boundary(["generational operational restorations calibration"])
        self.assertTrue(audit["ok"], audit)

    def test_underscore_and_hyphen_are_token_separators(self) -> None:
        self.assertEqual(M.report_tokens("metric_ratio cross-system p_value"), ["metric", "ratio", "cross", "system", "p", "value"])


class AdoptionAndLifecycleTests(unittest.TestCase):
    @staticmethod
    def _terminal_document(status: str, return_code: int) -> dict:
        return {
            "schema_version": "synthetic-terminal-v1", "status": status,
            "return_code": return_code, "attempt_003_authorized": False,
        }

    def _assert_persisted_terminal_extends_document(self, path: Path, expected: dict) -> dict:
        actual = json.loads(path.read_text(encoding="utf-8"))
        token = actual.pop("terminal_inode_ownership")
        self.assertEqual(actual, expected)
        info = os.lstat(str(path))
        self.assertEqual((token["device"], token["inode"]), (info.st_dev, info.st_ino))
        self.assertEqual(token["captured_from"], "O_EXCL-held staging fd before body write")
        self.assertTrue(token["final_inode_must_match"])
        self.assertTrue(M.terminal_embedded_ownership_audit(path)["ok"])
        return token

    def _assert_terminal_parent_fsync_reconcile(self, status: str, return_code: int) -> None:
        old_fsync = M.BASE.fsync_directory
        old_committed = M.BASE.TERMINAL_COMMITTED
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_result.json"
            injected = {"raised": False}
            def fail_after_terminal_exists(parent: Path) -> None:
                if parent == path.parent and path.exists() and not injected["raised"]:
                    injected["raised"] = True
                    raise OSError("injected terminal parent fsync failure")
                old_fsync(parent)
            document = self._terminal_document(status, return_code)
            try:
                M.BASE.fsync_directory = fail_after_terminal_exists
                M.BASE.TERMINAL_COMMITTED = False
                observed_code, identity, audit = M.commit_terminal_and_return(path, document)
                self.assertTrue(injected["raised"])
                self.assertEqual(observed_code, return_code)
                self.assertTrue(audit["ok"])
                self.assertFalse(audit["reconciled_after_publish_exception"])
                self.assertTrue(audit["semantic_commit_point_reached"])
                self.assertTrue(audit["directory_durability_confirmed"])
                self.assertEqual(audit["parent_directory_fsync"]["attempts"], 2)
                self.assertTrue(M.BASE.TERMINAL_COMMITTED)
                self._assert_persisted_terminal_extends_document(path, document)
                self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
            finally:
                M.BASE.fsync_directory = old_fsync
                M.BASE.TERMINAL_COMMITTED = old_committed

    def test_pass_terminal_parent_fsync_fault_never_returns_rc1(self) -> None:
        self._assert_terminal_parent_fsync_reconcile("PASS_SYNTHETIC", 0)

    def test_fail_terminal_parent_fsync_fault_returns_rc1(self) -> None:
        self._assert_terminal_parent_fsync_reconcile("FAIL_SYNTHETIC", 1)

    def test_persistent_parent_fsync_fault_is_reported_without_rc_json_divergence(self) -> None:
        old_fsync = M.BASE.fsync_directory
        old_committed = M.BASE.TERMINAL_COMMITTED
        try:
            def always_fail(_parent: Path) -> None:
                raise OSError("injected persistent parent fsync failure")
            M.BASE.fsync_directory = always_fail
            for status, return_code in (("PASS_SYNTHETIC", 0), ("FAIL_SYNTHETIC", 1)):
                with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "run_result.json"
                    document = self._terminal_document(status, return_code)
                    M.BASE.TERMINAL_COMMITTED = False
                    observed_code, identity, audit = M.commit_terminal_and_return(path, document)
                    self.assertEqual(observed_code, document["return_code"])
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["return_code"], observed_code)
                    self.assertTrue(audit["semantic_commit_point_reached"])
                    self.assertFalse(audit["directory_durability_confirmed"])
                    self.assertEqual(audit["parent_directory_fsync"]["attempts"], 3)
                    self.assertEqual(len(audit["parent_directory_fsync"]["errors"]), 3)
                    self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))
                    self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
                    public = M.terminal_commit_public_audit(audit)
                    self.assertFalse(public["directory_durability_confirmed"])
                    self.assertEqual(public["parent_directory_fsync"]["attempts"], 3)
        finally:
            M.BASE.fsync_directory = old_fsync
            M.BASE.TERMINAL_COMMITTED = old_committed

    def _assert_staging_fault_yields_only_formal_fail(self, hook_name: str) -> None:
        original = getattr(M, hook_name)
        old_committed = M.BASE.TERMINAL_COMMITTED
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_result.json"
            pass_document = self._terminal_document("PASS_SYNTHETIC", 0)
            failure_document = self._terminal_document("FAIL_SYNTHETIC", 1)
            injected = {"raised": False}

            if hook_name == "terminal_write_all":
                def fail_once(fd: int, payload: bytes) -> None:
                    if not injected["raised"]:
                        injected["raised"] = True
                        os.write(fd, payload[:max(1, len(payload) // 3)])
                        raise OSError("injected partial terminal staging write")
                    original(fd, payload)
            elif hook_name == "terminal_set_readonly":
                def fail_once(fd: int) -> None:
                    if not injected["raised"]:
                        injected["raised"] = True
                        os.fchmod(fd, 0o444)
                        raise OSError("injected post-fchmod terminal staging failure")
                    original(fd)
            elif hook_name == "terminal_file_fsync":
                def fail_once(fd: int) -> None:
                    if not injected["raised"]:
                        injected["raised"] = True
                        os.fsync(fd)
                        raise OSError("injected post-file-fsync terminal staging failure")
                    original(fd)
            else:
                raise AssertionError(hook_name)

            try:
                M.BASE.TERMINAL_COMMITTED = False
                setattr(M, hook_name, fail_once)
                with self.assertRaises(OSError):
                    M.commit_terminal_and_return(path, pass_document)
                self.assertTrue(injected["raised"])
                self.assertFalse(M.lexical_exists(path))
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
                self.assertFalse(M.BASE.TERMINAL_COMMITTED)
                setattr(M, hook_name, original)
                observed_code, identity, audit = M.commit_terminal_and_return(path, failure_document)
                self.assertEqual(observed_code, 1)
                self._assert_persisted_terminal_extends_document(path, failure_document)
                self.assertTrue(audit["ok"])
                self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
                self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["run_result.json"])
            finally:
                setattr(M, hook_name, original)
                M.BASE.TERMINAL_COMMITTED = old_committed

    def test_partial_body_write_fault_never_exposes_partial_final(self) -> None:
        self._assert_staging_fault_yields_only_formal_fail("terminal_write_all")

    def test_fchmod_fault_never_exposes_partial_final(self) -> None:
        self._assert_staging_fault_yields_only_formal_fail("terminal_set_readonly")

    def test_file_fsync_fault_never_exposes_partial_final(self) -> None:
        self._assert_staging_fault_yields_only_formal_fail("terminal_file_fsync")

    def test_run_once_pass_terminal_staging_faults_close_out_as_one_formal_fail(self) -> None:
        path_names = (
            "EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM",
            "PREFLIGHT_RESULT", "RUN_RESULT", "AUTHORITY", "LOCK",
        )
        function_names = (
            "held_snapshot_open", "held_snapshot_postflight", "close_held_snapshot",
            "post_pin_audit", "audit_completed_bundle", "relevant_processes",
            "direct_child_processes", "metrics_finite_nonnegative", "generate_analysis_bundle",
            "support_audit_from_bytes", "install_signal_handlers", "restore_signal_handlers",
        )
        original_paths = {name: getattr(M, name) for name in path_names}
        original_collect = M.collect_prestart
        original_adoption = M.attempt_001_adoption_audit
        original_authority = M.authority_audit
        original_functions = {name: getattr(M.BASE, name) for name in function_names}
        original_state = (M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED)
        scenarios = (
            "terminal_write_all", "terminal_set_readonly", "terminal_file_fsync",
            "postpublish_audit", "persistent_postcommit_audit",
            "postcommit_diagnostic_raise", "postcommit_foreign_staging",
            "postcommit_pending_signal", "pass_finalizer_fault", "fail_finalizer_fault",
            "exact_foreign_eexist", "hardlink_eexist", "hardlink_eexist_stage_removed",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "fresh-r2"; attempt = root / "attempt_002"
                authority = Path(directory) / "authority.json"
                authority.write_text("{}\n", encoding="utf-8"); os.chmod(authority, 0o444)
                lock = Path(directory) / "lock.json"
                lock.write_text('{"pinned_files":{}}\n', encoding="utf-8"); os.chmod(lock, 0o444)
                replacements = {
                    "EVIDENCE_ROOT": root, "ATTEMPT": attempt,
                    "ANALYSIS": attempt / "analysis-output", "FIGURES": attempt / "analysis-output/figures",
                    "START_CLAIM": attempt / "evaluation_start_claim.json",
                    "PREFLIGHT_RESULT": attempt / "preflight_result.json",
                    "RUN_RESULT": attempt / "run_result.json", "AUTHORITY": authority, "LOCK": lock,
                }
                authority_identity = M.BASE.file_identity(authority)
                evaluation = {
                    "support_audit": {"counts": {"common": M.BASE.COMMON_COUNT, "rpe_pairs": M.BASE.RPE_COUNT}},
                    "alignment": {
                        system: {
                            "primary_fixed_scale_se3": {"proper": True, "core_crosscheck_max_abs_m": 0.0},
                            "secondary_sim3_scale_diagnostic": {"proper": True},
                        } for system in ("hfnet", "supervins")
                    },
                    "metrics": {"statistical_boundary": {"cross_system_metric_contrast_computed": False}},
                    "report_boundary_audit": {"ok": True, "substring_matching_used": False},
                    "metrics_schema_audit": {"ok": True},
                    "input_audit": {"semantic_non_equivalence_disclosed": True},
                    "bundle_artifacts": {},
                    "figure_audits": {
                        "figure_01": {"equal_metric_aspect_all_axes": True, "gridline_coordinates_valid": True},
                        "figure_02": {"all_axis_lower_bounds_exact_zero": True, "gridline_coordinates_valid": True},
                    },
                }
                hook_name = {
                    "postpublish_audit": "terminal_document_audit",
                    "persistent_postcommit_audit": "terminal_owned_final_audit",
                    "postcommit_diagnostic_raise": "terminal_embedded_ownership_audit",
                    "postcommit_foreign_staging": "terminal_parent_fsync_with_retries",
                    "postcommit_pending_signal": "terminal_post_publish_hook",
                    "pass_finalizer_fault": "terminal_post_publish_hook",
                    "fail_finalizer_fault": "terminal_file_fsync",
                    "exact_foreign_eexist": "terminal_publish_noreplace",
                    "hardlink_eexist": "terminal_publish_noreplace",
                    "hardlink_eexist_stage_removed": "terminal_publish_noreplace",
                }.get(scenario, scenario)
                original_hook = getattr(M, hook_name)
                original_unlink = M.terminal_unlink_once
                injected = {"raised": False}
                cleanup_injected = {"raised": False}
                if scenario == "terminal_write_all":
                    def fail_once(fd: int, payload: bytes, _original=original_hook) -> None:
                        if not injected["raised"]:
                            injected["raised"] = True
                            os.write(fd, payload[:max(1, len(payload) // 5)])
                            raise OSError("run_once injected partial terminal write")
                        _original(fd, payload)
                elif scenario == "terminal_set_readonly":
                    def fail_once(fd: int, _original=original_hook) -> None:
                        if not injected["raised"]:
                            injected["raised"] = True
                            os.fchmod(fd, 0o444)
                            raise OSError("run_once injected post-fchmod failure")
                        _original(fd)
                elif scenario in ("terminal_file_fsync", "fail_finalizer_fault"):
                    def fail_once(fd: int, _original=original_hook) -> None:
                        if not injected["raised"]:
                            injected["raised"] = True
                            os.fsync(fd)
                            raise OSError("run_once injected post-file-fsync failure")
                        _original(fd)
                elif scenario == "postpublish_audit":
                    def fail_once(path: Path, document: dict, _original=original_hook) -> dict:
                        if path == replacements["RUN_RESULT"] and not injected["raised"]:
                            injected["raised"] = True
                            return {"ok": False, "observed": None, "error": "injected transient postpublish audit failure"}
                        return _original(path, document)
                elif scenario == "persistent_postcommit_audit":
                    audit_calls = {"count": 0}
                    def fail_once(path: Path, document: dict, expected_inode, maximum_attempts=3, _original=original_hook) -> dict:
                        if path == replacements["RUN_RESULT"]:
                            audit_calls["count"] += 1
                            if audit_calls["count"] >= 2:
                                injected["raised"] = True
                                return {"ok": False, "observed": None, "owned_inode_match": False,
                                        "error": "injected persistent postcommit audit failure"}
                        return _original(path, document, expected_inode, maximum_attempts)
                elif scenario == "postcommit_diagnostic_raise":
                    def fail_once(path: Path, _original=original_hook) -> dict:
                        if path == replacements["RUN_RESULT"] and not injected["raised"]:
                            injected["raised"] = True
                            raise RuntimeError("injected postcommit ownership diagnostic exception")
                        return _original(path)
                elif scenario == "postcommit_foreign_staging":
                    def fail_once(parent: Path, maximum_attempts=3, _original=original_hook) -> dict:
                        result = _original(parent, maximum_attempts)
                        if parent == replacements["ATTEMPT"] and not injected["raised"]:
                            injected["raised"] = True
                            M.terminal_staging_path(replacements["RUN_RESULT"]).write_bytes(b"foreign postcommit staging")
                        return result
                elif scenario == "pass_finalizer_fault":
                    def fail_once(_original=original_hook) -> None:
                        _original()
                elif scenario == "postcommit_pending_signal":
                    def fail_once(_original=original_hook) -> None:
                        _original()
                        M.BASE.PENDING_SIGNAL = 15
                        injected["raised"] = True
                else:
                    def fail_once(staging: Path, final: Path, _original=original_hook) -> None:
                        if not injected["raised"]:
                            injected["raised"] = True
                            if scenario == "exact_foreign_eexist":
                                M.BASE.write_bytes_exclusive(final, staging.read_bytes())
                            else:
                                os.link(str(staging), str(final), follow_symlinks=False)
                                if scenario == "hardlink_eexist_stage_removed":
                                    os.unlink(str(staging))
                        _original(staging, final)

                def unlink_fail_once(path: Path) -> None:
                    if scenario == "terminal_file_fsync" and not cleanup_injected["raised"]:
                        cleanup_injected["raised"] = True
                        raise OSError("run_once injected transient staging cleanup unlink failure")
                    original_unlink(path)
                try:
                    for name, value in replacements.items():
                        setattr(M, name, value)
                    M.configure_base()
                    M.collect_prestart = lambda require_authority=False: {
                        "ready": True,
                        "status": "GO_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START",
                        "failures": [], "pin_snapshot": {},
                        "authority": {"identity": authority_identity},
                        "attempt_001_failure_adoption_audit": {"ok": True},
                    }
                    M.attempt_001_adoption_audit = lambda: {"ok": True, "checks": {}, "failures": []}
                    M.authority_audit = lambda _lock: {"valid": True, "identity": authority_identity, "failures": []}
                    M.BASE.held_snapshot_open = lambda _paths, _pins: {"records": {
                        str(path.resolve()): {"payload": b""}
                        for path in (M.BASE.HF_TRAJECTORY, M.BASE.SV_TRAJECTORY, M.BASE.CAMERA_CSV, M.BASE.GT_CSV)
                    }}
                    M.BASE.held_snapshot_postflight = lambda _snapshot, _pins: {"ok": True, "checks": {}, "failures": []}
                    M.BASE.close_held_snapshot = lambda _snapshot: None
                    M.BASE.post_pin_audit = lambda _preflight: {"ok": True, "checks": {}, "failures": []}
                    M.BASE.audit_completed_bundle = lambda _artifacts: {"ok": True, "checks": {}, "failures": []}
                    M.BASE.relevant_processes = lambda: []
                    M.BASE.direct_child_processes = lambda: []
                    M.BASE.metrics_finite_nonnegative = lambda _metrics: True
                    M.BASE.support_audit_from_bytes = lambda *_payloads: {"ok": True}
                    M.BASE.generate_analysis_bundle = lambda _snapshot, _support: evaluation
                    M.BASE.install_signal_handlers = lambda: {}
                    M.BASE.restore_signal_handlers = lambda _previous: None
                    if scenario in ("pass_finalizer_fault", "fail_finalizer_fault"):
                        finalizer_faults = {"count": 0}
                        def finalizer_raise(*_args) -> None:
                            finalizer_faults["count"] += 1
                            injected["raised"] = True
                            raise RuntimeError("injected post-terminal finalizer failure")
                        M.BASE.close_held_snapshot = finalizer_raise
                        M.BASE.restore_signal_handlers = finalizer_raise
                    M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = None, False, False
                    setattr(M, hook_name, fail_once)
                    M.terminal_unlink_once = unlink_fail_once
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        observed_code = M.run_once(M.TOKEN)
                    terminal_path = attempt / "run_result.json"
                    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
                    self.assertTrue(injected["raised"])
                    expected_code = 0 if scenario in (
                        "postpublish_audit", "persistent_postcommit_audit",
                        "postcommit_diagnostic_raise", "postcommit_foreign_staging",
                        "postcommit_pending_signal", "pass_finalizer_fault",
                    ) else 1
                    self.assertEqual(observed_code, expected_code)
                    self.assertTrue(terminal["status"].startswith("PASS_" if expected_code == 0 else "FAIL_"))
                    self.assertEqual(terminal["return_code"], observed_code)
                    self.assertFalse(terminal["claim_boundary"]["attempt_003_authorized"])
                    self.assertTrue(M.terminal_embedded_ownership_audit(terminal_path)["ok"])
                    if scenario == "terminal_file_fsync":
                        self.assertTrue(cleanup_injected["raised"])
                    if scenario in ("exact_foreign_eexist", "hardlink_eexist", "hardlink_eexist_stage_removed"):
                        self.assertTrue(terminal["uncommitted_terminal_reclaim"]["ok"])
                        self.assertTrue(terminal["uncommitted_terminal_reclaim"]["entries"]["run_result.json"]["present_before"])
                    self.assertFalse(M.lexical_exists(M.terminal_staging_path(terminal_path)))
                    info = os.lstat(str(terminal_path))
                    self.assertTrue(stat.S_ISREG(info.st_mode))
                    self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink), (0o444, 1))
                    self.assertEqual(
                        sorted(str(path.relative_to(attempt)) for path in attempt.rglob("*") if path.is_file()),
                        ["evaluation_start_claim.json", "preflight_result.json", "run_result.json"],
                    )
                    stdout_rows = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
                    terminal_stdout = next(row for row in stdout_rows if "terminal_commit_audit" in row)
                    self.assertTrue(terminal_stdout["terminal_commit_audit"]["staging_absent"])
                    if scenario == "persistent_postcommit_audit":
                        self.assertFalse(terminal_stdout["terminal_commit_audit"]["post_commit_observation_confirmed"])
                    if scenario == "postcommit_foreign_staging":
                        self.assertTrue(terminal_stdout["terminal_commit_audit"]["post_commit_staging_absent"])
                    if scenario in ("pass_finalizer_fault", "fail_finalizer_fault"):
                        self.assertEqual(finalizer_faults["count"], 2)
                        self.assertTrue(any("post_terminal_finalizer_audit" in row for row in stdout_rows))
                finally:
                    setattr(M, hook_name, original_hook)
                    M.terminal_unlink_once = original_unlink
                    for name, value in original_paths.items():
                        setattr(M, name, value)
                    M.collect_prestart = original_collect
                    M.attempt_001_adoption_audit = original_adoption
                    M.authority_audit = original_authority
                    for name, value in original_functions.items():
                        setattr(M.BASE, name, value)
                    M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = original_state
                    M.configure_base()

    def test_rename_success_then_exception_reconciles_exact_pass_without_staging(self) -> None:
        original = M.terminal_post_publish_hook
        old_committed = M.BASE.TERMINAL_COMMITTED
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_result.json"
            document = self._terminal_document("PASS_SYNTHETIC", 0)
            injected = {"raised": False}
            def post_publish_raise() -> None:
                injected["raised"] = True
                raise OSError("injected exception after successful renameat2")
            try:
                M.terminal_post_publish_hook = post_publish_raise
                M.BASE.TERMINAL_COMMITTED = False
                observed_code, identity, audit = M.commit_terminal_and_return(path, document)
                self.assertTrue(injected["raised"])
                self.assertEqual(observed_code, 0)
                self.assertTrue(audit["reconciled_after_publish_exception"])
                self.assertIn("exception after successful renameat2", audit["publish_exception"])
                self._assert_persisted_terminal_extends_document(path, document)
                self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
            finally:
                M.terminal_post_publish_hook = original
                M.BASE.TERMINAL_COMMITTED = old_committed

    def test_renameat2_publish_is_noreplace_and_preserves_existing_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / ".staging"; final = root / "run_result.json"
            staging.write_bytes(b"new\n"); final.write_bytes(b"existing\n")
            with self.assertRaises(FileExistsError):
                M.terminal_publish_noreplace(staging, final)
            self.assertEqual(staging.read_bytes(), b"new\n")
            self.assertEqual(final.read_bytes(), b"existing\n")

    def test_exact_same_bytes_foreign_final_eexist_is_never_reconciled_as_owned(self) -> None:
        original_publish = M.terminal_publish_noreplace
        old_committed = M.BASE.TERMINAL_COMMITTED
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_result.json"
            document = self._terminal_document("PASS_SYNTHETIC", 0)
            observed = {}
            def inject_exact_foreign_final_then_publish(staging: Path, final: Path) -> None:
                staging_info = os.lstat(str(staging))
                observed["staging_inode"] = (staging_info.st_dev, staging_info.st_ino)
                M.BASE.write_bytes_exclusive(final, staging.read_bytes())
                foreign_info = os.lstat(str(final))
                observed["foreign_inode"] = (foreign_info.st_dev, foreign_info.st_ino)
                original_publish(staging, final)
            try:
                M.terminal_publish_noreplace = inject_exact_foreign_final_then_publish
                M.BASE.TERMINAL_COMMITTED = False
                with self.assertRaises(FileExistsError):
                    M.commit_terminal_and_return(path, document)
                self.assertNotEqual(observed["staging_inode"], observed["foreign_inode"])
                self.assertFalse(M.BASE.TERMINAL_COMMITTED)
                foreign_document = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(M.terminal_embedded_ownership_audit(path)["ok"])
                self.assertEqual(foreign_document["status"], document["status"])
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
                info = os.lstat(str(path))
                self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink), (0o444, 1))
            finally:
                M.terminal_publish_noreplace = original_publish
                M.BASE.TERMINAL_COMMITTED = old_committed

    def test_exact_same_bytes_staging_replacement_after_close_cannot_change_owned_token(self) -> None:
        original_audit = M.terminal_document_audit
        old_committed = M.BASE.TERMINAL_COMMITTED
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / "run_result.json"
            moved_owned = root / "owned-original-staging"
            document = self._terminal_document("PASS_SYNTHETIC", 0)
            observed = {}
            def replace_staging_before_path_audit(candidate: Path, value: dict) -> dict:
                if candidate == M.terminal_staging_path(path) and not observed:
                    original_info = os.lstat(str(candidate))
                    observed["owned_inode"] = (original_info.st_dev, original_info.st_ino)
                    os.rename(str(candidate), str(moved_owned))
                    M.BASE.write_bytes_exclusive(candidate, moved_owned.read_bytes())
                    replacement_info = os.lstat(str(candidate))
                    observed["replacement_inode"] = (replacement_info.st_dev, replacement_info.st_ino)
                return original_audit(candidate, value)
            try:
                M.terminal_document_audit = replace_staging_before_path_audit
                M.BASE.TERMINAL_COMMITTED = False
                with self.assertRaisesRegex(ValueError, "O_EXCL-opened inode"):
                    M.commit_terminal_and_return(path, document)
                self.assertNotEqual(observed["owned_inode"], observed["replacement_inode"])
                self.assertFalse(M.BASE.TERMINAL_COMMITTED)
                self.assertFalse(M.lexical_exists(path))
                self.assertFalse(M.lexical_exists(M.terminal_staging_path(path)))
                self.assertTrue(M.terminal_embedded_ownership_audit(moved_owned)["ok"])
            finally:
                M.terminal_document_audit = original_audit
                M.BASE.TERMINAL_COMMITTED = old_committed

    def test_addendum_truthfully_freezes_atomic_terminal_and_durability_boundary(self) -> None:
        addendum = json.loads(M.ADDENDUM.read_text(encoding="utf-8"))
        lifecycle = addendum["attempt_002_lifecycle"]
        self.assertIn("renameat2(RENAME_NOREPLACE)", lifecycle["terminal_result_creation"])
        self.assertIn("nofollow descriptor audit", lifecycle["terminal_semantic_commit_point"])
        self.assertIn("three times", lifecycle["terminal_parent_directory_durability"])
        self.assertIn("no claim of parent-directory crash durability", lifecycle["terminal_parent_directory_durability"])
        self.assertIn("terminal publication", addendum["corrective_delta"]["additive_control_plane_changes"])
        source = MODULE_PATH.read_text(encoding="utf-8")
        cache_code = source.index('COMMITTED_RETURN_CODE = int(document["return_code"])')
        cache_status = source.index('COMMITTED_STATUS = str(document.get("status", "COMMITTED_TERMINAL"))')
        commit_flag = source.index("BASE.TERMINAL_COMMITTED = True", cache_status)
        self.assertLess(cache_code, cache_status)
        self.assertLess(cache_status, commit_flag)
        self.assertIn("any_pre_semantic_commit_exception", json.dumps(addendum["failure_closeout"], sort_keys=True))

    def test_failure_adoption_is_exact_and_sealed(self) -> None:
        audit = M.attempt_001_adoption_audit()
        self.assertTrue(audit["ok"], audit["failures"])
        identity = audit["details"]["adoption_identity"]
        self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))

    def test_failure_adoption_self_hash(self) -> None:
        document = json.loads(M.FAILURE_ADOPTION.read_text(encoding="utf-8"))
        self.assertEqual(document["self_hash"], M.BASE.self_hash_object(document))

    def test_old_attempt_has_only_three_control_files(self) -> None:
        actual = sorted(str(path.relative_to(M.OLD_ATTEMPT)) for path in M.OLD_ATTEMPT.rglob("*") if path.is_file())
        self.assertEqual(actual, M.EXPECTED_OLD_FILE_SET)
        self.assertFalse(any(path.is_file() for path in (M.OLD_ATTEMPT / "analysis-output").rglob("*")))

    def test_exact_tree_rejects_extra_empty_directory_and_directory_symlink(self) -> None:
        def specs(root: Path, relatives) -> dict:
            result = {}
            for relative in relatives:
                info = os.lstat(str(root if relative == "." else root / relative))
                result[relative] = {"device": info.st_dev, "inode": info.st_ino,
                                    "mode": format(stat.S_IMODE(info.st_mode), "04o"), "nlink": info.st_nlink}
            return result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "old-root"; (root / "attempt_001/analysis-output/figures").mkdir(parents=True)
            control = root / "attempt_001/run_result.json"; control.write_text("{}\n", encoding="utf-8")
            expected_dirs = specs(root, (".", "attempt_001", "attempt_001/analysis-output", "attempt_001/analysis-output/figures"))
            expected_files = ["attempt_001/run_result.json"]
            self.assertTrue(M.exact_directory_tree_audit(root, expected_dirs, expected_files)["ok"])
            extra = root / "attempt_001/extra-empty"; extra.mkdir()
            self.assertFalse(M.exact_directory_tree_audit(root, expected_dirs, expected_files)["ok"])
            extra.rmdir()
            figures = root / "attempt_001/analysis-output/figures"; figures.rmdir()
            outside = Path(directory) / "outside-target"; outside.mkdir()
            figures.symlink_to(outside, target_is_directory=True)
            symlink_audit = M.exact_directory_tree_audit(root, expected_dirs, expected_files)
            self.assertFalse(symlink_audit["ok"])
            self.assertIn("directory:attempt_001/analysis-output/figures", symlink_audit["failures"])

    def test_old_terminal_is_formal_fail_and_old_authority_is_burned(self) -> None:
        terminal = json.loads(M.OLD_RUN_RESULT.read_text(encoding="utf-8"))
        authority = json.loads(M.OLD_AUTHORITY.read_text(encoding="utf-8"))
        self.assertEqual((terminal["status"], terminal["return_code"], terminal["retry_authorized"]),
                         ("FAIL_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS", 1, False))
        self.assertEqual((authority["attempt"], authority["maximum_evaluator_starts"], authority["retry_authorized"]), ("attempt_001", 1, False))

    def test_new_namespace_and_authority_are_absent(self) -> None:
        self.assertFalse(M.lexical_exists(M.EVIDENCE_ROOT))
        self.assertFalse(M.lexical_exists(M.START_CLAIM))
        self.assertFalse(M.lexical_exists(M.AUTHORITY))
        self.assertFalse(M.authority_audit({})["valid"])

    def test_new_token_and_lifecycle_are_distinct(self) -> None:
        old_lock = json.loads(M.OLD_LOCK.read_text(encoding="utf-8"))
        self.assertNotEqual(M.TOKEN_SHA256, old_lock["authorization_token_sha256"])
        source = MODULE_PATH.read_text(encoding="utf-8")
        for fragment in ('"attempt": "attempt_002"', '"prior_global_evaluation_start_count": 1', '"global_evaluation_start_count_after": 2'):
            self.assertIn(fragment, source)

    def test_authority_schema_explicitly_denies_attempt_003(self) -> None:
        expected = M.expected_authority_fields()
        self.assertFalse(expected["claim_boundary"]["attempt_003_authorized"])
        self.assertEqual(expected["attempt"], "attempt_002")
        self.assertEqual(expected["global_evaluator_start_count_after"], 2)
        identities = {key: {"sha256": "0" * 64, "size_bytes": 0} for key in M.AUTHORITY_IDENTITY_KEYS}
        valid = dict(expected, **identities)
        self.assertTrue(M.authority_schema_audit(valid)["ok"])
        invalid = json.loads(json.dumps(valid))
        invalid["claim_boundary"]["attempt_003_authorized"] = True
        self.assertFalse(M.authority_schema_audit(invalid)["ok"])
        self.assertIn("claim_boundary", M.authority_schema_audit(invalid)["failures"])
        extra = json.loads(json.dumps(valid)); extra["maximum_evaluator_starts"] = 99
        self.assertFalse(M.authority_schema_audit(extra)["ok"])
        self.assertIn("exact_top_level_allowlist", M.authority_schema_audit(extra)["failures"])
        extra_permission = json.loads(json.dumps(valid)); extra_permission["attempt_003_authorized"] = True
        self.assertFalse(M.authority_schema_audit(extra_permission)["ok"])

    def test_original_31_pin_map_and_digest(self) -> None:
        old_lock = json.loads(M.OLD_LOCK.read_text(encoding="utf-8"))
        self.assertEqual(len(old_lock["pinned_files"]), 31)
        self.assertEqual(M.BASE.canonical_pin_digest(old_lock["pinned_files"]), "9a9de036e3af55db187ff8d38f7b349e1969101525dc4b8b24864bee9ef07eee")

    def test_root_parent_fsync_failure_still_writes_one_terminal_fail(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT", "AUTHORITY")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect, old_fsync = M.collect_prestart, M.BASE.fsync_directory
        old_state = (M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh-r2"; attempt = root / "attempt_002"
            replacements = {
                "EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output",
                "FIGURES": attempt / "analysis-output/figures", "START_CLAIM": attempt / "evaluation_start_claim.json",
                "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json",
                "AUTHORITY": Path(directory) / "new-authority.json",
            }
            injected = {"raised": False}
            def fail_once(path: Path) -> None:
                if path == root.parent and not injected["raised"]:
                    injected["raised"] = True
                    raise OSError("attempt002 injected root parent fsync failure")
                old_fsync(path)
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                M.collect_prestart = lambda require_authority=False: {
                    "ready": True, "status": "GO_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START",
                    "failures": [], "pin_snapshot": {}, "authority": {}, "attempt_001_failure_adoption_audit": {},
                }
                M.BASE.fsync_directory = fail_once
                M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = None, False, False
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(M.run_once(M.TOKEN), 1)
                terminal_path = attempt / "run_result.json"
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
                self.assertTrue(injected["raised"])
                self.assertTrue(terminal["status"].startswith("FAIL_"))
                self.assertEqual(terminal["error"]["message"], "attempt002 injected root parent fsync failure")
                self.assertFalse(terminal["retry_authorized"])
                self.assertFalse(terminal["claim_boundary"]["attempt_003_authorized"])
                files = [path for path in attempt.rglob("*") if path.is_file()]
                self.assertEqual(files, [terminal_path])
                info = terminal_path.stat()
                self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink), (0o444, 1))
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart, M.BASE.fsync_directory = old_collect, old_fsync
                M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = old_state
                M.configure_base()

    def test_ordinary_exception_after_claim_writes_attempt003_denial(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT", "AUTHORITY", "LOCK")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect, old_open = M.collect_prestart, M.BASE.held_snapshot_open
        old_state = (M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh-r2"; attempt = root / "attempt_002"
            authority = Path(directory) / "new-authority.json"; authority.write_text("{}\n", encoding="utf-8"); os.chmod(authority, 0o444)
            lock = Path(directory) / "new-lock.json"; lock.write_text('{"pinned_files":{}}\n', encoding="utf-8"); os.chmod(lock, 0o444)
            replacements = {
                "EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output",
                "FIGURES": attempt / "analysis-output/figures", "START_CLAIM": attempt / "evaluation_start_claim.json",
                "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json",
                "AUTHORITY": authority, "LOCK": lock,
            }
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                M.collect_prestart = lambda require_authority=False: {
                    "ready": True, "status": "GO_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START",
                    "failures": [], "pin_snapshot": {}, "authority": {"identity": M.BASE.file_identity(authority, True)},
                    "attempt_001_failure_adoption_audit": {},
                }
                M.BASE.held_snapshot_open = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("attempt002 injected ordinary exception"))
                M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = None, False, False
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(M.run_once(M.TOKEN), 1)
                terminal = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
                self.assertEqual(terminal["error"]["message"], "attempt002 injected ordinary exception")
                self.assertFalse(terminal["claim_boundary"]["attempt_003_authorized"])
                self.assertIn("evaluation_start_claim.json", terminal["artifacts_before_result"])
                self.assertIn("preflight_result.json", terminal["artifacts_before_result"])
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart, M.BASE.held_snapshot_open = old_collect, old_open
                M.BASE.PENDING_SIGNAL, M.BASE.NAMESPACE_OWNED, M.BASE.TERMINAL_COMMITTED = old_state
                M.configure_base()


class ScientificInheritanceAndRenderedReportTests(unittest.TestCase):
    def test_scientific_functions_execute_from_sealed_base(self) -> None:
        expected = json.loads(M.ADDENDUM.read_text(encoding="utf-8"))["attempt_001_control_pins"]["runner"]
        identity = M.BASE.file_identity(M.BASE_RUNNER, include_seal=True)
        self.assertEqual(identity, {"sha256": expected["sha256"], "size_bytes": expected["size_bytes"],
                                    "mode": expected["required_mode"], "nlink": expected["required_nlink"]})

    def test_scientific_function_filenames_are_base_runner(self) -> None:
        for name in ("parse_hf", "parse_sv", "support_audit_from_bytes", "extract_common_positions", "evaluate_common_systems", "evaluate_one_system", "build_metrics_document", "trajectory_figure", "error_figure", "generate_analysis_bundle"):
            with self.subTest(name=name):
                self.assertEqual(Path(getattr(M.BASE, name).__code__.co_filename).resolve(), M.BASE_RUNNER.resolve())

    def test_common_support_constants_are_unchanged(self) -> None:
        self.assertEqual((M.BASE.COMMON_FIRST, M.BASE.COMMON_LAST, M.BASE.COMMON_STEP, M.BASE.COMMON_COUNT), (945, 3659, 2, 1358))
        self.assertEqual((M.BASE.RPE_INDEX_DELTA, M.BASE.RPE_CAMERA_DELTA, M.BASE.RPE_DELTA_NS, M.BASE.RPE_COUNT), (10, 20, 1_000_000_000, 1348))

    def test_actual_rendered_reports_pass_whole_token_gate(self) -> None:
        common = exact_synthetic_common()
        timestamp_support = {
            "ok": True, "failures": [],
            "counts": {"hfnet_rows": 2737, "supervins_rows": 1810, "camera_rows": 3682, "gt_rows": 36382, "common": 1358, "rpe_pairs": 1348},
            "common": {"first_camera_row": 945, "last_camera_row": 3659, "step": 2, "first_timestamp_ns": M.BASE.COMMON_FIRST_NS, "last_timestamp_ns": M.BASE.COMMON_LAST_NS, "span_ns": M.BASE.COMMON_SPAN_NS},
            "coverage": {"hfnet_full_output_rows": 2737, "hfnet_input_camera_rows": 3682, "supervins_generated_rows": 1810, "supervins_expected_odd_rows": 1841},
            "scientific_values_parsed": False, "alignment_or_error_computed": False,
        }
        old_paths = (M.BASE.ATTEMPT, M.BASE.ANALYSIS, M.BASE.FIGURES)
        old_extract = M.BASE.extract_common_positions
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "attempt_002"; analysis = attempt / "analysis-output"; figures = analysis / "figures"
            figures.mkdir(parents=True)
            snapshot = {"records": {str(path.resolve()): {"opened_identity": {"sha256": "synthetic", "size_bytes": 0}} for path in M.BASE.SNAPSHOT_PATHS}}
            try:
                M.BASE.ATTEMPT, M.BASE.ANALYSIS, M.BASE.FIGURES = attempt, analysis, figures
                M.BASE.extract_common_positions = lambda _snapshot: common
                result = M.BASE.generate_analysis_bundle(snapshot, timestamp_support)
                reports = [(analysis / name).read_text(encoding="utf-8") for name in ("analysis-report.md", "stats-appendix.md", "figure-catalog.md")]
                self.assertIn("generation failures", reports[0])
                self.assertTrue(M.validate_report_boundary(reports)["ok"])
                self.assertTrue(result["report_boundary_audit"]["ok"])
                self.assertFalse(result["report_boundary_audit"]["substring_matching_used"])
                self.assertTrue(result["metrics_schema_audit"]["ok"])
                self.assertEqual(len(result["bundle_artifacts"]), 12)
            finally:
                M.BASE.ATTEMPT, M.BASE.ANALYSIS, M.BASE.FIGURES = old_paths
                M.BASE.extract_common_positions = old_extract

    def test_wrapper_does_not_import_subprocess_or_redefine_science(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^import subprocess|^from subprocess")
        for definition in ("parse_hf", "parse_sv", "evaluate_one_system", "trajectory_figure", "error_figure", "generate_analysis_bundle"):
            self.assertNotIn("def {}(".format(definition), source)


if __name__ == "__main__":
    unittest.main()
