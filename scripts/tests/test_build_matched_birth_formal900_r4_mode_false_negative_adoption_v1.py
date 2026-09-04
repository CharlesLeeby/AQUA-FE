#!/usr/bin/env python3
"""Adversarial tests for the r4 mode-false-negative adoption builder."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest import mock

from scripts import (
    build_matched_birth_formal900_r4_mode_false_negative_adoption_v1 as adoption,
)


class SyntheticR4:
    def __init__(self, root: Path) -> None:
        self.root = root
        os.chmod(self.root, 0o700)
        for arm in adoption.ARM_DIRECTORIES.values():
            directory = root / arm
            directory.mkdir(mode=0o700)
            private = directory / "private_work"
            private.mkdir(mode=0o700)
        for name in adoption.ROOT_FILES:
            self._write(root / name, b"root:" + name.encode() + b"\n", 0o444)
        for arm in adoption.ARM_DIRECTORIES.values():
            for name in adoption.ARM_FILES:
                mode = (
                    0o444
                    if name in adoption.ARM_GOVERNANCE_FILES
                    else 0o664
                )
                self._write(
                    root / arm / name,
                    b"arm:" + arm.encode() + b":" + name.encode() + b"\n",
                    mode,
                )

    @staticmethod
    def _write(path: Path, payload: bytes, mode: int) -> None:
        path.write_bytes(payload)
        os.chmod(path, mode)


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir=adoption.WORKSPACE_ROOT / "experiments"
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SyntheticR4(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def snapshot(self) -> dict[str, object]:
        return adoption._snapshot_r4(self.root, require_frozen_identity=False)

    def test_exact_tree_is_held_as_five_directories_and_nineteen_files(self) -> None:
        snapshot = self.snapshot()
        try:
            self.assertEqual(len(snapshot["directories"]), 5)
            self.assertEqual(len(snapshot["files"]), 19)
            self.assertEqual(len(snapshot["inventory"]), 24)
            adoption._finish_snapshot(snapshot)
        finally:
            adoption._close_snapshot(snapshot)

    def test_result_role_must_be_0664(self) -> None:
        path = self.root / "xfeat_r4/export_manifest.json"
        os.chmod(path, 0o444)
        with self.assertRaisesRegex(adoption.AdoptionError, "role mode drift"):
            self.snapshot()

    def test_governance_role_must_be_0444(self) -> None:
        path = self.root / "gftt_r4/launcher_rc_receipt.json"
        os.chmod(path, 0o664)
        with self.assertRaisesRegex(adoption.AdoptionError, "role mode drift"):
            self.snapshot()

    def test_extra_root_entry_is_rejected(self) -> None:
        (self.root / "extra").write_bytes(b"unexpected")
        with self.assertRaisesRegex(adoption.AdoptionError, "root exact listing"):
            self.snapshot()

    def test_nonempty_private_work_is_rejected(self) -> None:
        (self.root / "gftt_r4/private_work/orphan").write_bytes(b"x")
        with self.assertRaisesRegex(adoption.AdoptionError, "private work"):
            self.snapshot()

    def test_symlink_substitution_is_rejected(self) -> None:
        path = self.root / "xfeat_r4/features.bag"
        path.unlink()
        path.symlink_to(self.root / "gftt_r4/features.bag")
        with self.assertRaises((OSError, adoption.AdoptionError)):
            self.snapshot()

    def test_visible_inode_replacement_after_snapshot_is_rejected(self) -> None:
        snapshot = self.snapshot()
        path = self.root / "xfeat_r4/raw_diagnostics.csv"
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        os.chmod(replacement, 0o664)
        os.replace(replacement, path)
        try:
            with self.assertRaisesRegex(
                adoption.AdoptionError,
                "visible inode drift|final inventory|single-link regular inode",
            ):
                adoption._finish_snapshot(snapshot)
        finally:
            adoption._close_snapshot(snapshot)


class FirewallAndAuthorizationTests(unittest.TestCase):
    def test_final_corrected_auditor_identity_is_hard_pinned_and_live(self) -> None:
        payload = adoption.CORRECTED_AUDITOR.read_bytes()
        self.assertEqual(
            adoption.EXPECTED_CORRECTED_AUDITOR,
            {
                "path": str(adoption.CORRECTED_AUDITOR),
                "size_bytes": len(payload),
                "sha256": __import__("hashlib").sha256(payload).hexdigest(),
            },
        )

    def test_published_canonical_keysets_are_disjoint_from_outcome_values(self) -> None:
        self.assertIn("continuation_authorization", adoption.RECORD_KEYS)
        self.assertEqual(
            adoption.ADOPTION_RECORD_KEYS,
            {"path", "schema_version", "builder_identity"},
        )
        self.assertEqual(
            adoption.CONTINUATION_SEAL_KEYS,
            {
                "path",
                "required_pre_run_state",
                "publication_mode_octal",
                "write_once_no_clobber",
            },
        )
        self.assertTrue(
            adoption.FORBIDDEN_RECORD_KEYS.isdisjoint(
                adoption.CONTINUATION_AUTHORIZATION_KEYS
            )
        )

    def test_outcome_firewall_accepts_inventory_only(self) -> None:
        adoption._validate_outcome_firewall(
            {
                "source_namespace": {
                    "exact_tree_inventory": [
                        {"path": "/held/features.bag", "sha256": "0" * 64}
                    ]
                },
                "outcome_firewall": {
                    "result_values_exposed_in_permit": False
                },
            }
        )

    def test_outcome_firewall_rejects_nested_result_value_key(self) -> None:
        with self.assertRaisesRegex(adoption.AdoptionError, "forbidden result keys"):
            adoption._validate_outcome_firewall(
                {"innocent_wrapper": {"metrics": {"published_frames": 900}}}
            )

    def test_authorized_argv_is_exact_transformation(self) -> None:
        old = [
            "/usr/bin/python3.8",
            "-B",
            "-m",
            "scripts.audit_matched_birth_rawlk_pair_formal_v2",
            "--action",
            "audit",
            "--scientific-argument",
            "held",
            "--post-run-audit-json",
            str(adoption.OLD_ERROR_SEAL),
        ]
        result = adoption._build_authorized_argv(
            {"authoritative_commands": {"post_run_audit": {"argv": old}}}
        )
        self.assertEqual(
            result[:6],
            [
                "/usr/bin/python3.8",
                "-B",
                "-m",
                "scripts.audit_matched_birth_rawlk_pair_formal_r4_modefix_v1",
                "--action",
                "audit",
            ],
        )
        self.assertEqual(
            result[-4:],
            [
                "--continuation-adoption-json",
                str(adoption.DEFAULT_OUTPUT),
                "--continuation-seal-json",
                str(adoption.CONTINUATION_SEAL),
            ],
        )
        self.assertEqual(
            result[result.index("--post-run-audit-json") + 1],
            str(adoption.OLD_ERROR_SEAL),
        )

    def test_external_held_file_final_mode_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=adoption.WORKSPACE_ROOT / "papers"
        ) as temporary:
            path = Path(temporary).resolve() / "held.json"
            path.write_bytes(b"{}\n")
            os.chmod(path, 0o444)
            held = adoption._open_external(
                path, required_mode=0o444, label="synthetic external"
            )
            try:
                os.chmod(path, 0o664)
                with self.assertRaisesRegex(adoption.AdoptionError, "held bytes"):
                    adoption._finish_external(held, label="synthetic external")
            finally:
                os.close(held["descriptor"])


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir=adoption.WORKSPACE_ROOT / "papers"
        )
        self.parent = Path(self.temporary.name).resolve()
        self.output = self.parent / "permit.json"
        self.record = {
            "schema_version": "synthetic",
            "status": "TEST_ONLY",
            "outcome_firewall": {"result_values_exposed_in_permit": False},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_write_once_is_canonical_0444_and_no_clobber(self) -> None:
        device_id = int(os.lstat(self.parent).st_dev)
        with mock.patch.object(adoption, "DEFAULT_OUTPUT", self.output), mock.patch.object(
            adoption, "EXPECTED_DEVICE_ID", device_id
        ):
            identity = adoption.write_once(self.output, self.record)
            self.assertEqual(identity["path"], str(self.output))
            self.assertEqual(stat.S_IMODE(os.lstat(self.output).st_mode), 0o444)
            self.assertEqual(
                self.output.read_bytes(), adoption._canonical_bytes(self.record)
            )
            with self.assertRaisesRegex(
                adoption.AdoptionError, "namespace is already consumed"
            ):
                adoption.write_once(self.output, self.record)

    def test_wrong_output_path_is_rejected_without_creation(self) -> None:
        wrong = self.parent / "wrong.json"
        with self.assertRaisesRegex(adoption.AdoptionError, "not the frozen"):
            adoption.write_once(wrong, self.record)
        self.assertFalse(wrong.exists())

    def test_main_holds_publication_guard_across_write_and_postcheck(self) -> None:
        events: list[str] = []
        guard = {"synthetic": True}
        identity = {
            "path": str(adoption.DEFAULT_OUTPUT),
            "size_bytes": 1,
            "sha256": "0" * 64,
        }
        with mock.patch.object(
            adoption, "build_record", return_value=self.record
        ), mock.patch.object(
            adoption,
            "_open_publication_guard",
            side_effect=lambda record: events.append("open") or guard,
        ), mock.patch.object(
            adoption,
            "_finish_publication_guard",
            side_effect=lambda observed: events.append("finish"),
        ), mock.patch.object(
            adoption,
            "write_once",
            side_effect=lambda output, record, **kwargs: (
                events.append("write"),
                kwargs["held_source_postcheck"](),
                identity,
            )[-1],
        ), mock.patch.object(
            adoption,
            "_close_publication_guard",
            side_effect=lambda observed: events.append("close"),
        ):
            with redirect_stdout(io.StringIO()):
                rc = adoption.main(["--action", "write-once"])
        self.assertEqual(rc, 0)
        self.assertEqual(events, ["open", "finish", "write", "finish", "close"])

    def test_postguard_failure_leaves_non_adoption_terminal_and_no_pass(self) -> None:
        device_id = int(os.lstat(self.parent).st_dev)
        events: list[str] = []
        stderr = io.StringIO()
        stdout = io.StringIO()

        def finish(_guard: object) -> None:
            events.append("finish")
            if len(events) == 2:
                raise adoption.AdoptionError("synthetic postguard drift")

        with mock.patch.object(adoption, "DEFAULT_OUTPUT", self.output), mock.patch.object(
            adoption, "EXPECTED_DEVICE_ID", device_id
        ), mock.patch.object(
            adoption, "build_record", return_value=self.record
        ), mock.patch.object(
            adoption, "_open_publication_guard", return_value={"guard": True}
        ), mock.patch.object(
            adoption, "_finish_publication_guard", side_effect=finish
        ), mock.patch.object(adoption, "_close_publication_guard"):
            with redirect_stdout(stdout), mock.patch("sys.stderr", stderr):
                rc = adoption.main(["--action", "write-once"])
        self.assertEqual(rc, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("ADOPTION_BLOCKED", stderr.getvalue())
        terminal = json.loads(self.output.read_text())
        self.assertNotEqual(terminal["schema_version"], adoption.SCHEMA_VERSION)
        self.assertFalse(terminal["adoption_authorized"])
        self.assertEqual(stat.S_IMODE(os.lstat(self.output).st_mode), 0o444)

    def test_replacement_after_final_fsync_is_rejected_without_adoption_bytes(self) -> None:
        device_id = int(os.lstat(self.parent).st_dev)

        def replace_visible() -> None:
            replacement = self.parent / "replacement.json"
            replacement.write_bytes(b'{"schema_version":"foreign"}\n')
            os.chmod(replacement, 0o444)
            os.replace(replacement, self.output)

        with mock.patch.object(adoption, "DEFAULT_OUTPUT", self.output), mock.patch.object(
            adoption, "EXPECTED_DEVICE_ID", device_id
        ):
            with self.assertRaisesRegex(adoption.AdoptionError, "identity drift"):
                adoption.write_once(
                    self.output,
                    self.record,
                    after_final_fsync_hook=replace_visible,
                )
        self.assertNotEqual(
            self.output.read_bytes(), adoption._canonical_bytes(self.record)
        )


class LiveNamespaceBoundaryTests(unittest.TestCase):
    def test_no_continuation_artifact_or_vins_namespace_exists(self) -> None:
        self.assertFalse(adoption.DEFAULT_OUTPUT.exists())
        self.assertFalse(adoption.CONTINUATION_SEAL.exists())
        for path in adoption.VINS_RUN_DIRECTORIES:
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
