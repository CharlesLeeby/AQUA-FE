#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import audit_matched_birth_rawlk_pair_formal_v2 as audit
from scripts import build_matched_birth_rawlk_pair_formal_freeze_v2 as builder
from scripts import run_matched_birth_arm_once_v1 as launcher


def _namespace_arguments(root: Path) -> dict[str, object]:
    root.mkdir(mode=0o700)
    arms = {}
    commands = {}
    starts = {}
    rcs = {}
    names = {
        "feature_bag": "features.bag",
        "manifest_json": "export_manifest.json",
        "diagnostics_csv": "raw_diagnostics.csv",
        "legacy_primitive_manifest": "legacy_primitive_manifest.json",
        "private_work_directory": "private_work",
        "attempt_json": "producer_attempt.json",
    }
    for arm_id, directory in audit.R4_ARM_DIRECTORIES.items():
        arm_root = root / directory
        arm_root.mkdir(mode=0o700)
        arms[arm_id] = {role: arm_root / name for role, name in names.items()}
        commands[arm_id] = arm_root / "command_contract.json"
        starts[arm_id] = arm_root / "launcher_start_receipt.json"
        rcs[arm_id] = arm_root / "launcher_rc_receipt.json"
    return {
        "freeze_json": root / audit.R4_ROOT_ARTIFACT_NAMES["freeze"],
        "pre_run_start_receipt": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["pre_run_start_receipt"]
        ),
        "post_run_pair_seal": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
        ),
        "arm_paths": arms,
        "command_contract_paths": commands,
        "launcher_start_receipts": starts,
        "launcher_rc_receipts": rcs,
    }


class FormalFreezeBuilderTests(unittest.TestCase):
    def test_mode_contract_is_formal900_only(self) -> None:
        self.assertEqual(
            builder.MODE_CONTRACTS,
            {"formal900": {"allow_prefix": False, "expected_frames": 900}},
        )
        choices = next(
            action.choices
            for action in builder.build_parser()._actions
            if action.dest == "mode"
        )
        self.assertEqual(tuple(choices), ("formal900",))

    def test_exact_fresh_r4_namespace_and_names_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r4"
            args = _namespace_arguments(root)
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root):
                builder._validate_exact_fresh_r4_namespace(args)

    def test_nonempty_r4_arm_and_wrong_global_name_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r4"
            args = _namespace_arguments(root)
            (root / "xfeat_r4" / "unexpected").write_bytes(b"x")
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), self.assertRaisesRegex(
                builder.FreezeBuildError, "not fresh"
            ):
                builder._validate_exact_fresh_r4_namespace(args)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r4"
            args = _namespace_arguments(root)
            args["freeze_json"] = root / "freeze.json"
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), self.assertRaisesRegex(
                builder.FreezeBuildError, "root path mismatch"
            ):
                builder._validate_exact_fresh_r4_namespace(args)

    def test_probe_mode_rejected_before_adoption_or_bag_work(self) -> None:
        with mock.patch.dict(
            builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
        ), mock.patch.object(
            audit, "_validate_formal900_adoption"
        ) as adoption, self.assertRaisesRegex(
            builder.FreezeBuildError, "unsupported matched freeze mode"
        ):
            builder.build_payload(
                mode="probe16",
                freeze_json=Path("/unused"),
                source_bag=Path("/unused"),
                raw_bag=Path("/unused"),
                camera_yaml=Path("/unused"),
                arm_paths={},
                command_contract_paths={},
                launcher_start_receipts={},
                launcher_rc_receipts={},
                pre_run_start_receipt=Path("/unused"),
                post_run_pair_seal=Path("/unused"),
                feature_topic="/feature_tracker/feature",
                image_topic="/camera/image_raw",
            )
        adoption.assert_not_called()


if __name__ == "__main__":
    unittest.main()
