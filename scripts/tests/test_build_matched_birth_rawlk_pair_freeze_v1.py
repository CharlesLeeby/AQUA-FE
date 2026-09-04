#!/usr/bin/env python3

from __future__ import annotations

import copy
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from scripts import audit_matched_birth_rawlk_pair_v1 as audit
from scripts import build_matched_birth_rawlk_pair_freeze_v1 as builder
from scripts import matched_birth_rawlk_core_v1 as core
from scripts import run_matched_birth_arm_once_v1 as launcher


def _fixed_rows(count: int) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = [
        {
            "raw_index": index,
            "header_stamp_ns": 1_000 + index,
            "published": bool(index % 2),
            "adaptive_clahe_applied": False,
            "raw_image_sha256": f"{index:064x}"[-64:],
            "processed_image_sha256": f"{index + 1:064x}"[-64:],
        }
        for index in range(count)
    ]
    return rows, {
        "source_total_published_frames": 900,
        "selected_published_frames": count // 2,
        "cutoff_feature_record_stamp_ns": (2_000 if count == 32 else None),
        "raw_row_count": count,
        "published_raw_indices_sha256": "1" * 64,
        "raw_schedule_sha256": core._diagnostics_schedule_stream(rows),
        "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(rows),
        "image_shapes_hw": [[8, 8]],
    }


def _detector_metadata(arm_id: str) -> dict[str, object]:
    runtime = {"detect_calls": 0, "candidate_total": 0}
    if arm_id == audit.XFEAT_ARM:
        runtime["detect_ms"] = {
            group: {
                "count": 0,
                "median_ms": None,
                "p90_ms": None,
                "total_ms": 0.0,
            }
            for group in ("warmup", "steady_state", "all")
        }
    return {"runtime": runtime}


def _arguments(root: Path, mode: str) -> dict[str, object]:
    source = root / "source.bag"
    raw = root / "raw.bag"
    camera = root / "camera.yaml"
    source.write_bytes(b"source")
    raw.write_bytes(b"raw")
    camera.write_bytes(b"camera")
    arm_paths = {}
    contracts = {}
    starts = {}
    rcs = {}
    for label, arm_id in (("xfeat", audit.XFEAT_ARM), ("gftt", audit.GFTT_ARM)):
        run = root / label
        run.mkdir()
        arm_paths[arm_id] = {
            "feature_bag": run / "features.bag",
            "manifest_json": run / "manifest.json",
            "diagnostics_csv": run / "diagnostics.csv",
            "legacy_primitive_manifest": run / "legacy.json",
            "private_work_directory": run / "work",
            "attempt_json": run / "attempt.json",
        }
        contracts[arm_id] = run / "command.json"
        starts[arm_id] = run / "launcher-start.json"
        rcs[arm_id] = run / "launcher-rc.json"
    return {
        "mode": mode,
        "freeze_json": root / "freeze.json",
        "source_bag": source,
        "raw_bag": raw,
        "camera_yaml": camera,
        "arm_paths": arm_paths,
        "command_contract_paths": contracts,
        "launcher_start_receipts": starts,
        "launcher_rc_receipts": rcs,
        "pre_run_start_receipt": root / "audit-start.json",
        "post_run_pair_seal": root / "audit-seal.json",
        "feature_topic": "/feature_tracker/feature",
        "image_topic": "/camera/image_raw",
    }


def _filesystem_paths(root: Path) -> list[Path]:
    root.mkdir(mode=0o700)
    paths = [root / name for name in ("freeze.json", "audit-start.json", "audit-seal.json")]
    for arm in ("xfeat", "gftt"):
        parent = root / arm
        parent.mkdir(mode=0o700)
        paths.extend(
            parent / name
            for name in (
                "features.bag", "manifest.json", "diagnostics.csv", "legacy.json",
                "private-work", "attempt.json", "command.json",
                "launcher-start.json", "launcher-rc.json",
            )
        )
    if len(paths) != 21:
        raise AssertionError("synthetic filesystem path fixture is not exact 21")
    return paths


class OutcomeBlindFreezeBuilderTests(unittest.TestCase):
    def _patches(self, mode: str):
        count = 32 if mode == "probe16" else 1800
        rows, reconstruction = _fixed_rows(count)
        core_runtime = {"pycache_prefix": str(launcher.PYCACHE_PREFIX)}
        runtime = {
            "core_runtime": copy.deepcopy(core_runtime),
            "pycache_prefix": str(launcher.PYCACHE_PREFIX),
        }
        common = {
            "runtime": copy.deepcopy(core_runtime),
            "carrier": {"lk_win_size": [21, 21]},
        }
        incident_identity = {
            "path": str(audit.INFRASTRUCTURE_INCIDENT_PATH),
            "size_bytes": audit.INFRASTRUCTURE_INCIDENT_SIZE,
            "sha256": audit.INFRASTRUCTURE_INCIDENT_SHA256,
        }
        filesystem_envelope = {
            "schema_version": audit.ARTIFACT_FILESYSTEM_ENVELOPE_SCHEMA,
            "static_contract": {
                "namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
            },
            "builder_prepublication_capability_probe": (
                audit._expected_artifact_capability_attestation()
            ),
        }
        return (
            mock.patch.object(
                audit, "_audit_runtime_observation", return_value=runtime
            ),
            mock.patch.object(core, "common_contract", return_value=common),
            mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=(rows, reconstruction),
            ),
            mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ),
            mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ),
            mock.patch.dict(
                builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
            ),
            mock.patch.object(
                audit,
                "_validate_infrastructure_incident",
                return_value={
                    "identity": incident_identity,
                    "authorized_namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
                },
            ),
            mock.patch.object(
                audit, "_artifact_filesystem_envelope",
                return_value=filesystem_envelope,
            ),
            mock.patch.object(
                builder,
                "_probe_artifact_publication_capabilities",
                return_value=audit._expected_artifact_capability_attestation(),
            ),
            mock.patch.multiple(
                audit,
                _validate_continuation_mode_and_inputs=mock.DEFAULT,
                _validate_continuation_scientific_projection=mock.DEFAULT,
            ),
        )

    def test_probe16_and_formal900_have_exact_independent_dynamic_shapes(self) -> None:
        for mode, expected_rows in (("probe16", 32), ("formal900", 1800)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                args = _arguments(Path(temporary), mode)
                patches = self._patches(mode)
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                    freeze, _contracts = builder.build_payload(**args)
                self.assertEqual(
                    freeze["fixed_semantics"]["expected_raw_frames"], expected_rows
                )
                for arm_id in audit.EXPECTED_ARMS:
                    arm = freeze["arms"][arm_id]
                    self.assertEqual(
                        arm["dynamic_scalar_paths"],
                        sorted(
                            audit._mandatory_dynamic_rules(
                                arm_id,
                                allow_prefix=(mode == "probe16"),
                                expected_frames=16 if mode == "probe16" else 900,
                            )
                        ),
                    )
                    self.assertEqual(
                        len(arm["manifest_template"]["raw_frame_diagnostics"]),
                        expected_rows,
                    )
                    self.assertTrue(
                        all(not path.exists() for path in args["arm_paths"][arm_id].values())
                    )

    def test_r3_continuation_rejects_formal900_before_bag_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "formal900")
            locked = {
                "source_feature_bag": audit._file_identity(args["source_bag"]),
                "raw_image_bag": audit._file_identity(args["raw_bag"]),
                "camera_yaml": audit._file_identity(args["camera_yaml"]),
            }
            gate = {
                "identity": {},
                "continuation_contract": {
                    "mode": {
                        "allow_prefix_nonformal": True,
                        "expected_published_frames": 16,
                        "expected_raw_frames": 32,
                    },
                    "locked_inputs": locked,
                },
            }
            with mock.patch.dict(
                builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
            ), mock.patch.object(
                audit, "_validate_infrastructure_incident", return_value=gate
            ), mock.patch.object(
                audit, "_artifact_filesystem_envelope", return_value={}
            ), mock.patch.object(
                audit, "_audit_runtime_observation"
            ) as runtime, mock.patch.object(
                audit, "_reconstruct_common_diagnostics"
            ) as reconstruction, self.assertRaisesRegex(
                audit.AuditFailure, "continuation probe mode"
            ):
                builder.build_payload(**args)
            runtime.assert_not_called()
            reconstruction.assert_not_called()
            self.assertTrue(
                all(
                    not os.path.lexists(path)
                    for path in builder._governed_future_paths(args)
                )
            )

    def test_r3_continuation_rejects_changed_input_before_bag_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            locked = {
                "source_feature_bag": audit._file_identity(args["source_bag"]),
                "raw_image_bag": audit._file_identity(args["raw_bag"]),
                "camera_yaml": audit._file_identity(args["camera_yaml"]),
            }
            changed_raw = Path(temporary) / "changed-raw.bag"
            changed_raw.write_bytes(b"changed raw")
            args["raw_bag"] = changed_raw
            gate = {
                "identity": {},
                "continuation_contract": {
                    "mode": {
                        "allow_prefix_nonformal": True,
                        "expected_published_frames": 16,
                        "expected_raw_frames": 32,
                    },
                    "locked_inputs": locked,
                },
            }
            with mock.patch.dict(
                builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
            ), mock.patch.object(
                audit, "_validate_infrastructure_incident", return_value=gate
            ), mock.patch.object(
                audit, "_artifact_filesystem_envelope", return_value={}
            ), mock.patch.object(
                audit, "_audit_runtime_observation"
            ) as runtime, mock.patch.object(
                audit, "_reconstruct_common_diagnostics"
            ) as reconstruction, self.assertRaisesRegex(
                audit.AuditFailure, "continuation locked inputs"
            ):
                builder.build_payload(**args)
            runtime.assert_not_called()
            reconstruction.assert_not_called()

    def test_no_detector_constructor_or_future_outcome_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], mock.patch.object(
                audit.matched_xfeat, "MatchedXFeatDetector",
                side_effect=AssertionError("detector construction forbidden"),
            ), mock.patch.object(
                audit.matched_gftt, "GFTTBirthDetector",
                side_effect=AssertionError("detector construction forbidden"),
            ):
                freeze, _contracts = builder.build_payload(**args)
            self.assertEqual(freeze["status"], "FROZEN")

    def test_runtime_drift_after_locked_bag_reconstruction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            rows, reconstruction = _fixed_rows(32)
            core_runtime = {"pycache_prefix": str(launcher.PYCACHE_PREFIX)}
            runtime = {
                "core_runtime": copy.deepcopy(core_runtime),
                "pycache_prefix": str(launcher.PYCACHE_PREFIX),
            }
            drifted = copy.deepcopy(runtime)
            drifted["core_runtime"]["contract_pass"] = False
            common = {
                "runtime": copy.deepcopy(core_runtime),
                "carrier": {"lk_win_size": [21, 21]},
            }
            with mock.patch.object(
                audit,
                "_audit_runtime_observation",
                side_effect=[runtime, drifted],
            ), mock.patch.object(
                core, "common_contract", return_value=common
            ), mock.patch.object(
                audit,
                "_reconstruct_common_diagnostics",
                return_value=(rows, reconstruction),
            ), mock.patch.object(
                core.primitive,
                "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive,
                "_nonfeature_digest",
                return_value={
                    "message_count": 0,
                    "ordered_sha256": "0" * 64,
                    "topics": {},
                },
            ), mock.patch.dict(
                builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
            ), mock.patch.object(
                audit,
                "_validate_infrastructure_incident",
                return_value={"identity": {}},
            ), mock.patch.object(
                audit, "_artifact_filesystem_envelope", return_value={}
            ), mock.patch.multiple(
                audit,
                _validate_continuation_mode_and_inputs=mock.DEFAULT,
                _validate_continuation_scientific_projection=mock.DEFAULT,
            ), self.assertRaisesRegex(
                builder.FreezeBuildError,
                "runtime drift after locked-bag reconstruction",
            ):
                builder.build_payload(**args)

    def test_o_excl_contract_and_freeze_publication_is_not_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], mock.patch.object(
                audit, "_validate_freeze", return_value={"pass": True}
            ):
                result = builder.build_and_write(**args)
            self.assertEqual(result["status"], "PASS_OUTCOME_BLIND_FREEZE_BUILT")
            for path in (
                Path(args["freeze_json"]),
                *(
                    Path(value)
                    for value in args["command_contract_paths"].values()
                ),
            ):
                observed = os.lstat(path)
                self.assertEqual(stat.S_IMODE(observed.st_mode), 0o444)
                self.assertEqual(observed.st_nlink, 1)
            frozen = Path(args["freeze_json"]).read_bytes()
            patches = self._patches("probe16")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], self.assertRaises(
                builder.FreezeBuildError
            ):
                builder.build_and_write(**args)
            self.assertEqual(Path(args["freeze_json"]).read_bytes(), frozen)

    def test_topics_and_locked_input_aliases_fail_before_any_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            args["image_topic"] = "/wrong"
            with mock.patch.dict(
                builder.os.environ, launcher.FROZEN_ENVIRONMENT, clear=True
            ), self.assertRaisesRegex(builder.FreezeBuildError, "image topic"):
                builder.build_payload(**args)
            self.assertFalse(Path(args["freeze_json"]).exists())
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            args["raw_bag"] = args["source_bag"]
            patches = self._patches("probe16")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], self.assertRaisesRegex(
                builder.FreezeBuildError, "locked input"
            ):
                builder.build_payload(**args)

    def test_environment_is_exact_and_orphan_contract_is_not_a_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            wrong_environment = dict(launcher.FROZEN_ENVIRONMENT)
            wrong_environment["UNAUTHORIZED"] = "1"
            with patches[0], patches[1], patches[2], patches[3], patches[4], mock.patch.dict(
                builder.os.environ, wrong_environment, clear=True
            ), self.assertRaisesRegex(builder.FreezeBuildError, "exact frozen environment"):
                builder.build_payload(**args)
            self.assertFalse(Path(args["freeze_json"]).exists())

        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            original_write = builder._write_exclusive
            writes = {"count": 0}

            def fail_after_first_contract(path, payload):
                writes["count"] += 1
                if writes["count"] == 2:
                    raise OSError("synthetic second-contract publication failure")
                return original_write(path, payload)

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], mock.patch.object(
                audit, "_validate_freeze", return_value={"pass": True}
            ), mock.patch.object(
                builder, "_write_exclusive", side_effect=fail_after_first_contract
            ), self.assertRaisesRegex(OSError, "second-contract"):
                builder.build_and_write(**args)

            self.assertTrue(
                Path(args["command_contract_paths"][audit.XFEAT_ARM]).is_file()
            )
            self.assertFalse(
                Path(args["command_contract_paths"][audit.GFTT_ARM]).exists()
            )
            self.assertFalse(Path(args["freeze_json"]).exists())
            with mock.patch.object(
                audit,
                "_audit_runtime_observation",
                return_value={
                    "core_runtime": {
                        "pycache_prefix": str(launcher.PYCACHE_PREFIX)
                    },
                    "pycache_prefix": str(launcher.PYCACHE_PREFIX),
                },
            ), self.assertRaises(audit.AuditFailure):
                audit.check_pre_run_start(
                    freeze_json=Path(args["freeze_json"]),
                    source_bag=Path(args["source_bag"]),
                    raw_bag=Path(args["raw_bag"]),
                    camera_yaml=Path(args["camera_yaml"]),
                    xfeat_bag=Path(args["arm_paths"][audit.XFEAT_ARM]["feature_bag"]),
                    xfeat_manifest=Path(args["arm_paths"][audit.XFEAT_ARM]["manifest_json"]),
                    xfeat_diagnostics=Path(args["arm_paths"][audit.XFEAT_ARM]["diagnostics_csv"]),
                    xfeat_legacy_manifest=Path(args["arm_paths"][audit.XFEAT_ARM]["legacy_primitive_manifest"]),
                    xfeat_work_directory=Path(args["arm_paths"][audit.XFEAT_ARM]["private_work_directory"]),
                    xfeat_attempt=Path(args["arm_paths"][audit.XFEAT_ARM]["attempt_json"]),
                    gftt_bag=Path(args["arm_paths"][audit.GFTT_ARM]["feature_bag"]),
                    gftt_manifest=Path(args["arm_paths"][audit.GFTT_ARM]["manifest_json"]),
                    gftt_diagnostics=Path(args["arm_paths"][audit.GFTT_ARM]["diagnostics_csv"]),
                    gftt_legacy_manifest=Path(args["arm_paths"][audit.GFTT_ARM]["legacy_primitive_manifest"]),
                    gftt_work_directory=Path(args["arm_paths"][audit.GFTT_ARM]["private_work_directory"]),
                    gftt_attempt=Path(args["arm_paths"][audit.GFTT_ARM]["attempt_json"]),
                    feature_topic=args["feature_topic"],
                    image_topic=args["image_topic"],
                    allow_prefix=True,
                    expected_frames=16,
                    pre_run_start_receipt=Path(args["pre_run_start_receipt"]),
                    post_run_pair_seal=Path(args["post_run_pair_seal"]),
                )

    def test_write_exclusive_detects_wrong_same_length_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claimed.json"
            payload = {"schema_version": "test", "value": "expected"}
            encoded = audit._canonical_bytes(payload)

            def wrong_write(descriptor, _payload):
                os.write(descriptor, b"x" * len(encoded))

            with mock.patch.object(
                audit, "_write_all", side_effect=wrong_write
            ), self.assertRaisesRegex(builder.FreezeBuildError, "bytes changed"):
                builder._write_exclusive(path, payload)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b"x" * len(encoded))

    def test_future_path_appearance_blocks_freeze_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            original_write = builder._write_exclusive
            writes = {"count": 0}
            appeared = Path(args["pre_run_start_receipt"])

            def inject_before_commit(path, payload):
                identity = original_write(path, payload)
                writes["count"] += 1
                if writes["count"] == 2:
                    appeared.write_bytes(b"foreign\n")
                return identity

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], mock.patch.object(
                audit, "_validate_freeze", return_value={"pass": True}
            ), mock.patch.object(
                builder, "_write_exclusive", side_effect=inject_before_commit
            ), self.assertRaisesRegex(builder.FreezeBuildError, "appeared before commit"):
                builder.build_and_write(**args)
            self.assertTrue(appeared.exists())
            self.assertFalse(Path(args["freeze_json"]).exists())

    def test_ext4_contract_and_disposable_capability_probe_leave_no_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            baseline = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root):
                envelope = audit._artifact_filesystem_envelope(paths)
                observed = builder._probe_artifact_publication_capabilities(paths)
            self.assertEqual(
                envelope["builder_prepublication_capability_probe"], observed
            )
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                baseline,
            )
            self.assertTrue(all(not os.path.lexists(path) for path in paths))

    def test_capability_probe_precedes_validation_and_all_governed_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            events: list[str] = []
            original_write = builder._write_exclusive
            original_absence = builder._assert_absent_paths
            incident_result = patches[6].kwargs["return_value"]
            filesystem_result = patches[7].kwargs["return_value"]

            def record_incident():
                events.append("incident")
                return copy.deepcopy(incident_result)

            def record_filesystem(_paths):
                events.append("filesystem")
                return copy.deepcopy(filesystem_result)

            def record_absence(paths, *, label):
                events.append(f"absence:{label}")
                return original_absence(paths, label=label)

            def record_probe(_paths):
                events.append("probe")
                return audit._expected_artifact_capability_attestation()

            def record_validate(*_args, **_kwargs):
                events.append("validate")
                return {"pass": True}

            def record_write(path, payload):
                if Path(path) == Path(args["freeze_json"]):
                    role = "freeze"
                elif Path(path) == Path(args["command_contract_paths"][audit.XFEAT_ARM]):
                    role = "xfeat"
                elif Path(path) == Path(args["command_contract_paths"][audit.GFTT_ARM]):
                    role = "gftt"
                else:
                    role = "unexpected"
                events.append(f"write:{role}")
                return original_write(path, payload)

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[9], mock.patch.object(
                audit, "_validate_infrastructure_incident", side_effect=record_incident
            ), mock.patch.object(
                audit, "_artifact_filesystem_envelope", side_effect=record_filesystem
            ), mock.patch.object(
                builder, "_probe_artifact_publication_capabilities",
                side_effect=record_probe,
            ), mock.patch.object(
                audit, "_validate_freeze", side_effect=record_validate,
            ), mock.patch.object(
                builder, "_assert_absent_paths", side_effect=record_absence,
            ), mock.patch.object(
                builder, "_write_exclusive", side_effect=record_write,
            ):
                builder.build_and_write(**args)
            self.assertEqual(
                events,
                [
                    "incident", "filesystem",
                    "absence:pre-capability-probe", "probe",
                    "absence:post-capability-probe", "validate",
                    "absence:pre-publication", "write:xfeat", "write:gftt",
                    "absence:pre-freeze-commit", "incident", "filesystem",
                    "write:freeze",
                ],
            )

    def test_non_ext4_and_wrong_path_count_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), mock.patch.object(
                audit, "_statfs_magic", return_value=0x65735546
            ), self.assertRaisesRegex(audit.AuditFailure, "not ext4"):
                audit._artifact_filesystem_contract(paths)
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), self.assertRaisesRegex(
                audit.AuditFailure, "exactly 21"
            ):
                audit._artifact_filesystem_contract(paths[:-1])

    def test_parent_permissions_device_and_mount_must_match_namespace_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            gftt = root / "gftt"
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root):
                gftt.chmod(0o500)
                try:
                    with self.assertRaisesRegex(audit.AuditFailure, "parent contract"):
                        audit._artifact_filesystem_contract(paths)
                finally:
                    gftt.chmod(0o700)

                real_lstat = audit.os.lstat

                def different_device(path):
                    observed = real_lstat(path)
                    if Path(path) == gftt:
                        values = list(observed)
                        values[2] = int(observed.st_dev) + 1
                        return os.stat_result(values)
                    return observed

                with mock.patch.object(
                    audit.os, "lstat", side_effect=different_device
                ), self.assertRaisesRegex(
                    audit.AuditFailure, "multiple devices|namespace-root device"
                ):
                    audit._artifact_filesystem_contract(paths)

                root_mount = audit._mountinfo_contract(root)

                def distinct_mount(path):
                    if Path(path) == gftt:
                        return {**root_mount, "mount_point": "/synthetic-read-only-bind"}
                    return root_mount

                with mock.patch.object(
                    audit, "_mountinfo_contract", side_effect=distinct_mount
                ), self.assertRaisesRegex(audit.AuditFailure, "distinct mount"):
                    audit._artifact_filesystem_contract(paths)

    def test_unidentified_probe_artifact_is_retained_and_blocks_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            real_fstat = builder.os.fstat
            calls = {"count": 0}

            def fail_first_fstat(descriptor):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise OSError("synthetic first-fstat failure")
                return real_fstat(descriptor)

            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), mock.patch.object(
                builder.os, "fstat", side_effect=fail_first_fstat
            ), self.assertRaisesRegex(builder.FreezeBuildError, "retained as failure evidence"):
                builder._probe_artifact_publication_capabilities(paths)
            residues = list(root.glob(".publication-capability-*"))
            self.assertEqual(len(residues), 1)
            with mock.patch.object(
                audit, "ARTIFACT_NAMESPACE_ROOT", root
            ), self.assertRaisesRegex(builder.FreezeBuildError, "stale capability probe"):
                builder._probe_artifact_publication_capabilities(paths)

    def test_fchmod_capability_failure_cleans_without_governed_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            baseline = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            real_fchmod = os.fchmod

            def force_wrong_mode(descriptor, _mode):
                return real_fchmod(descriptor, 0o755)

            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), mock.patch.object(
                builder.os, "fchmod", side_effect=force_wrong_mode
            ), mock.patch.object(builder, "_write_exclusive") as governed_write, self.assertRaisesRegex(
                builder.FreezeBuildError, "fchmod"
            ):
                builder._probe_artifact_publication_capabilities(paths)
            governed_write.assert_not_called()
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                baseline,
            )

    def test_build_and_write_capability_failure_precedes_validation_and_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = _arguments(Path(temporary), "probe16")
            patches = self._patches("probe16")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[9], mock.patch.object(
                builder,
                "_probe_artifact_publication_capabilities",
                side_effect=builder.FreezeBuildError("synthetic fchmod capability failure"),
            ), mock.patch.object(audit, "_validate_freeze") as validate, mock.patch.object(
                builder, "_write_exclusive"
            ) as governed_write, self.assertRaisesRegex(
                builder.FreezeBuildError, "fchmod capability"
            ):
                builder.build_and_write(**args)
            validate.assert_not_called()
            governed_write.assert_not_called()
            self.assertTrue(
                all(not os.path.lexists(path) for path in builder._governed_future_paths(args))
            )

    def test_probe_file_failure_after_o_excl_is_still_inode_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "r2"
            paths = _filesystem_paths(root)
            baseline = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            original_create = builder._create_probe_file
            calls = {"count": 0}

            def create_then_fail(path, payload, owned):
                identity = original_create(path, payload, owned)
                calls["count"] += 1
                if calls["count"] == 1:
                    raise builder.FreezeBuildError("synthetic after-create failure")
                return identity

            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root), mock.patch.object(
                builder, "_create_probe_file", side_effect=create_then_fail
            ), self.assertRaisesRegex(builder.FreezeBuildError, "after-create"):
                builder._probe_artifact_publication_capabilities(paths)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                baseline,
            )


if __name__ == "__main__":
    unittest.main()
