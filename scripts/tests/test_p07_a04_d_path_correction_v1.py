from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from scripts import build_p07_a04_d_path_correction_lock_v1 as builder
from scripts import run_p07_a04_d_path_correction_v1 as runtime


class PathAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "workspace"
        self.target = self.base / "external/datasets"
        self.root.mkdir()
        self.target.mkdir(parents=True)
        (self.root / "datasets").symlink_to(self.target, target_is_directory=True)
        self.archive_rel = Path(
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_sequence_4_raw_data.tar.gz"
        )
        self.gt_rel = Path(
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_04.txt"
        )
        self.archive = self.root / self.archive_rel
        self.gt = self.root / self.gt_rel
        self.archive.parent.mkdir(parents=True)
        self.gt.parent.mkdir(parents=True)
        self.archive.write_bytes(b"archive")
        self.gt.write_bytes(b"gt")
        with mock.patch.object(builder, "ROOT", self.root):
            identity = builder.datasets_symlink_identity(self.root / "datasets")
        self.payload = {
            "datasets_symlink_identity": identity,
            "datasets_external_file_allowlist": [
                self._record(self.archive_rel, self.archive),
                self._record(self.gt_rel, self.gt),
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _record(relative: Path, path: Path) -> dict[str, object]:
        return {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "source": "q55_recovery_lock.artifacts",
        }

    def test_accepts_only_exact_archive_and_gt_through_frozen_top_link(self) -> None:
        for relative in (self.archive_rel, self.gt_rel):
            observed = runtime.corrected_workspace_path(
                self.payload, relative.as_posix(), "data", root=self.root
            )
            self.assertEqual(observed, self.root / relative)

    def test_rejects_absolute_dotdot_and_unlisted_dataset_path(self) -> None:
        extra = self.root / "datasets/extra.txt"
        extra.write_text("extra", encoding="utf-8")
        for value, pattern in (
            (str(self.archive.resolve()), "workspace-relative"),
            ("datasets/../outside.txt", "forbidden"),
            ("datasets/extra.txt", "exact archive/GT allowlist"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                runtime.d_v4.ResolutionViolation, pattern
            ):
                runtime.corrected_workspace_path(
                    self.payload, value, "data", root=self.root
                )

    def test_rejects_leaf_symlink_even_when_allowlisted(self) -> None:
        target = self.target / "real-archive"
        target.write_bytes(b"archive")
        self.archive.unlink()
        self.archive.symlink_to(target)
        with mock.patch.object(builder, "ROOT", self.root):
            self.payload[
                "datasets_symlink_identity"
            ] = builder.datasets_symlink_identity(self.root / "datasets")
        with self.assertRaisesRegex(
            runtime.d_v4.ResolutionViolation, "nested or leaf"
        ):
            runtime.corrected_workspace_path(
                self.payload, self.archive_rel.as_posix(), "archive", root=self.root
            )

    def test_rejects_nested_dataset_symlink(self) -> None:
        actual = self.target / "actual"
        actual.mkdir()
        nested = self.target / "nested"
        nested.symlink_to(actual, target_is_directory=True)
        leaf = actual / "file.bin"
        leaf.write_bytes(b"x")
        relative = Path("datasets/nested/file.bin")
        payload = dict(self.payload)
        with mock.patch.object(builder, "ROOT", self.root):
            payload["datasets_symlink_identity"] = builder.datasets_symlink_identity(
                self.root / "datasets"
            )
        payload["datasets_external_file_allowlist"] = [
            self._record(relative, self.root / relative),
            self.payload["datasets_external_file_allowlist"][1],
        ]
        with self.assertRaisesRegex(runtime.d_v4.ResolutionViolation, "nested or leaf"):
            runtime.corrected_workspace_path(
                payload, relative.as_posix(), "nested", root=self.root
            )

    def test_rejects_any_other_workspace_symlink(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "file").write_text("x", encoding="utf-8")
        (self.root / "other").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(runtime.d_v4.ResolutionViolation, "forbidden"):
            runtime.corrected_workspace_path(
                self.payload, "other/file", "other", root=self.root
            )

    def test_internal_regular_file_is_accepted(self) -> None:
        path = self.root / "papers/evidence.json"
        path.parent.mkdir()
        path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(
            runtime.corrected_workspace_path(
                self.payload, "papers/evidence.json", "internal", root=self.root
            ),
            path,
        )

    def test_patch_context_restores_old_helper_on_exception(self) -> None:
        original = runtime.d_v4._workspace_path
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with mock.patch.object(runtime.contract, "ROOT", self.root):
                with runtime.patched_legacy_workspace_path(self.payload):
                    self.assertIsNot(runtime.d_v4._workspace_path, original)
                    raise RuntimeError("boom")
        self.assertIs(runtime.d_v4._workspace_path, original)


class PrefixAndRecoveryFreezeTests(unittest.TestCase):
    def test_prefix_allows_append_but_rejects_rewrite_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = root / "stream.csv"
            prefix = b"a,b\n1,2\n"
            stream.write_bytes(prefix)
            snapshot = {
                "path": "stream.csv",
                "sha256": hashlib.sha256(prefix).hexdigest(),
                "size_bytes": len(prefix),
            }
            stream.write_bytes(prefix + b"3,4\n")
            runtime._validate_prefix(snapshot, root)
            stream.write_bytes(b"a,b\n9,2\n3,4\n")
            with self.assertRaisesRegex(runtime.PathCorrectionError, "prefix drift"):
                runtime._validate_prefix(snapshot, root)
            stream.write_bytes(prefix[:-1])
            with self.assertRaisesRegex(runtime.PathCorrectionError, "prefix drift"):
                runtime._validate_prefix(snapshot, root)

    def test_old_recovery_non_dataset_artifact_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "workspace"
            target = base / "data"
            root.mkdir()
            target.mkdir()
            (root / "datasets").symlink_to(target, target_is_directory=True)
            internal = root / "scripts/frozen.py"
            internal.parent.mkdir()
            internal.write_text("frozen\n", encoding="utf-8")
            archive = root / "datasets/archive.tar.gz"
            gt = root / "datasets/gt.txt"
            archive.write_bytes(b"archive")
            gt.write_bytes(b"gt")
            stream = root / "registry.csv"
            stream.write_bytes(b"header\nrow\n")
            with mock.patch.object(builder, "ROOT", root):
                identity = builder.datasets_symlink_identity(root / "datasets")
                allowlist = [
                    {
                        "path": "datasets/archive.tar.gz",
                        "sha256": builder.sha256(archive),
                        "size_bytes": archive.stat().st_size,
                        "source": "q55_recovery_lock.artifacts",
                    },
                    {
                        "path": "datasets/gt.txt",
                        "sha256": builder.sha256(gt),
                        "size_bytes": gt.stat().st_size,
                        "source": "q55_recovery_lock.artifacts",
                    },
                ]
                recovery = {
                    "artifacts": [
                        {
                            "path": "scripts/frozen.py",
                            "sha256": builder.sha256(internal),
                            "size_bytes": internal.stat().st_size,
                        },
                        *[
                            {
                                "path": record["path"],
                                "sha256": record["sha256"],
                                "size_bytes": record["size_bytes"],
                            }
                            for record in allowlist
                        ],
                    ],
                    "mutable_stream_prefix_snapshots": [
                        {
                            "path": "registry.csv",
                            "sha256": hashlib.sha256(b"header\n").hexdigest(),
                            "size_bytes": len(b"header\n"),
                        }
                    ],
                }
                with mock.patch.object(
                    builder.recovery_runtime,
                    "validate_lock_payload",
                    return_value=recovery,
                ):
                    builder.verify_frozen_recovery_contract(
                        recovery, allowlist, identity
                    )
                    internal.write_text("drift!\n", encoding="utf-8")
                    with self.assertRaisesRegex(
                        builder.CorrectionLockError, "artifact drift"
                    ):
                        builder.verify_frozen_recovery_contract(
                            recovery, allowlist, identity
                        )
                    internal.write_text("frozen\n", encoding="utf-8")
                    archive.write_bytes(b"ARCHIVE")  # same size, different SHA-256
                    with self.assertRaisesRegex(
                        builder.CorrectionLockError, "datasets artifact drift"
                    ):
                        builder.verify_frozen_recovery_contract(
                            recovery, allowlist, identity
                        )


class FormalLockValidationTests(unittest.TestCase):
    def _payload(self, root: Path) -> dict[str, object]:
        event_rows = []
        frontend = []
        artifact_paths = {
            "scripts/build_p07_a04_d_path_correction_lock_v1.py",
            "scripts/run_p07_a04_d_path_correction_v1.py",
            "scripts/tests/test_p07_a04_d_path_correction_v1.py",
            "scripts/resolve_p07_d_applicability_v4.py",
            "scripts/build_p07_d_resolution_lock_v4.py",
            "scripts/resolve_p07_d_applicability_v2.py",
            "scripts/build_p07_d_resolution_lock_v2.py",
            "scripts/resolve_p07_d_applicability_v3.py",
            "scripts/build_p07_d_resolution_lock_v3.py",
            "scripts/tests/test_p07_d_resolution_v3.py",
            "scripts/run_p07_q55_a04_layout_replacement_v1.py",
            builder.display_path(builder.RECOVERY_LOCK),
            builder.display_path(builder.RECOVERY_REGISTRATION),
            builder.display_path(builder.RECOVERY_CLOSEOUT),
        }
        for index in (55, 56, 57):
            event = {"registry_event_id": f"run-{index}_e02", "status": "COMPLETED"}
            event_rows.append(event)
            manifest_rel = f"evidence/q{index}_output.sha256"
            feature = {
                "path": f"logs/q{index}/features.bag",
                "sha256": (
                    builder.EXPECTED_ZERO_ACTION_BAG_SHA256
                    if index in (55, 57)
                    else f"{index:064x}"[-64:]
                ),
                "size_bytes": (
                    builder.EXPECTED_ZERO_ACTION_BAG_SIZE
                    if index in (55, 57)
                    else index
                ),
            }
            manifest = root / manifest_rel
            manifest.parent.mkdir(exist_ok=True)
            manifest.write_text(
                f"{feature['sha256']}  {feature['path']}\n", encoding="utf-8"
            )
            audit_rel = f"evidence/q{index}_audit.json"
            input_rel = f"evidence/q{index}_input.sha256"
            artifact_paths.update({audit_rel, input_rel, manifest_rel})
            frontend.append(
                {
                    "queue_index": index,
                    "terminal_registry_event": event,
                    "feature_bag": feature,
                    "audit": {"path": audit_rel},
                    "input_hash_manifest": {"path": input_rel},
                    "output_hash_manifest": {"path": manifest_rel},
                }
            )
        pending = {"resolution": "PENDING_APPLICABILITY", "sequence": "A04"}
        snapshots = [
            {"path": builder.display_path(builder.RUN_REGISTRY)},
            {"path": builder.display_path(builder.REPLACEMENT_LEDGER)},
            {"path": builder.display_path(builder.APPLICABILITY)},
            {"path": builder.display_path(builder.governance.D_QUEUE)},
        ]
        payload: dict[str, object] = {
            "schema_version": builder.SCHEMA,
            "status": builder.STATUS,
            "window_id": builder.WINDOW_ID,
            "expected_d_decision": "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1",
            "action_order": builder.ACTION_ORDER,
            "outcome_boundary": builder.OUTCOME_BOUNDARY,
            "trajectory_outcome_read": False,
            "vins_execution_allowed": False,
            "resume_queue_indices": [58, 59, 60],
            "authorized_wrapper_actions": [
                "preflight-d",
                "build-d",
                "resolve-d",
                "resume-preflight",
                "resume-execute",
            ],
            "path_policy": {
                "only_allowed_symlink_entry": "datasets",
                "only_allowed_symlink_depth": 1,
                "datasets_paths_not_in_exact_allowlist_allowed": False,
                "leaf_symlinks_allowed": False,
                "nested_symlinks_allowed": False,
            },
            "datasets_external_file_allowlist": [
                {"path": "datasets/archive"},
                {"path": "datasets/gt"},
            ],
            "datasets_symlink_identity": {},
            "artifacts": [{"path": path} for path in sorted(artifact_paths)],
            "mutable_stream_prefix_snapshots": snapshots,
            "frontend_terminal_evidence": frontend,
            "applicability_precondition": {"matching_rows": [pending]},
            "zero_action_identity": {
                "accepted_learned_born_lineage_count": 0,
                "p_feature_bag": frontend[0]["feature_bag"],
                "b1_feature_bag": frontend[2]["feature_bag"],
                "byte_identical_sha256": builder.EXPECTED_ZERO_ACTION_BAG_SHA256,
                "byte_identical_size_bytes": builder.EXPECTED_ZERO_ACTION_BAG_SIZE,
            },
        }
        payload[builder.SELF_HASH_FIELD] = builder.document_hash(payload)
        payload["_test_registry_rows"] = event_rows
        payload["_test_pending"] = pending
        payload[builder.SELF_HASH_FIELD] = builder.document_hash(payload)
        return payload

    def test_validates_exact_prefix_events_and_transitive_feature_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self._payload(root)
            registry = payload.pop("_test_registry_rows")
            pending = payload.pop("_test_pending")
            payload[builder.SELF_HASH_FIELD] = builder.document_hash(payload)

            def prefix_rows(snapshot, _root):
                if snapshot["path"] == builder.display_path(builder.RUN_REGISTRY):
                    return registry
                if snapshot["path"] == builder.display_path(builder.APPLICABILITY):
                    return [pending]
                raise AssertionError(snapshot)

            with mock.patch.object(runtime, "_validate_symlink_identity"), mock.patch.object(
                runtime, "_validate_artifact_record"
            ), mock.patch.object(runtime, "_validate_prefix"), mock.patch.object(
                runtime, "_csv_prefix_rows", side_effect=prefix_rows
            ), mock.patch.object(
                runtime, "_allowlist_matches_recovery"
            ):
                runtime.validate_lock_payload(payload, root=root)
                manifest = root / payload["frontend_terminal_evidence"][0][
                    "output_hash_manifest"
                ]["path"]
                manifest.write_text("wrong\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    runtime.PathCorrectionError, "transitive"
                ):
                    runtime.validate_lock_payload(payload, root=root)


class EnhancedLockAndTerminalStateTests(unittest.TestCase):
    def test_invalid_temp_enhanced_lock_is_never_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "a04_v4.json"
            payload: dict[str, object] = {}
            document = {"schema_version": "test"}
            with mock.patch.object(runtime, "ENHANCED_D_LOCK", target), mock.patch.object(
                runtime,
                "patched_legacy_workspace_path",
                return_value=nullcontext(),
            ), mock.patch.object(
                runtime.d_v4,
                "load_resolution_lock",
                return_value=document,
            ), mock.patch.object(
                runtime,
                "_validate_enhanced_payload",
                side_effect=runtime.PathCorrectionError("invalid"),
            ):
                with self.assertRaisesRegex(runtime.PathCorrectionError, "invalid"):
                    runtime._validate_then_publish_enhanced_d_lock(payload, document)
            self.assertFalse(os.path.lexists(target))
            self.assertEqual(list(target.parent.glob("*.partial.correction.*")), [])

    def test_valid_temp_is_hardlinked_no_clobber_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "a04_v4.json"
            document = {"schema_version": "test", "value": 1}

            def load(_window: str):
                path = runtime.d_v4.resolution_lock_path(runtime.WINDOW_ID)
                return json.loads(path.read_text(encoding="utf-8"))

            with mock.patch.object(runtime, "ENHANCED_D_LOCK", target), mock.patch.object(
                runtime,
                "patched_legacy_workspace_path",
                return_value=nullcontext(),
            ), mock.patch.object(
                runtime.d_v4, "load_resolution_lock", side_effect=load
            ), mock.patch.object(
                runtime, "_validate_enhanced_payload", side_effect=lambda _p, value: value
            ):
                observed = runtime._validate_then_publish_enhanced_d_lock({}, document)
            self.assertEqual(observed, document)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), document)
            before = target.read_bytes()
            with mock.patch.object(runtime, "ENHANCED_D_LOCK", target):
                with self.assertRaises(FileExistsError):
                    runtime._validate_then_publish_enhanced_d_lock({}, document)
            self.assertEqual(target.read_bytes(), before)

    def test_resolve_accepts_append_only_pending_plus_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not_applicable.json"
            pending = {"resolution": "PENDING_APPLICABILITY"}
            terminal = {
                "resolution": "NOT_APPLICABLE",
                "resolver_hash": "lock-hash",
            }
            result = {
                "status": "PASS_NOT_APPLICABLE",
                "resolution": "NOT_APPLICABLE",
                "accepted_learned_born_lineage_count": 0,
                "resolver_hash": "lock-hash",
                "parent_p_run_id": "replacement",
            }
            output.write_text(json.dumps(result), encoding="utf-8")
            payload = {
                "recovery_evidence": {
                    "replacement_q55_terminal_event": {"run_id": "replacement"}
                }
            }
            with mock.patch.object(
                runtime, "load_enhanced_d_lock", return_value={"resolution_lock_hash": "lock-hash"}
            ), mock.patch.object(runtime, "_d_collision_paths", return_value=[runtime.ENHANCED_D_LOCK]), mock.patch.object(
                runtime,
                "_application_state",
                side_effect=[([pending], []), ([pending], [terminal])],
            ), mock.patch.object(
                runtime,
                "patched_legacy_workspace_path",
                return_value=nullcontext(),
            ), mock.patch.object(
                runtime.d_v4, "append_resolution", return_value=result
            ), mock.patch.object(
                runtime.d_v2, "output_paths", return_value=(output, None)
            ):
                self.assertEqual(runtime.resolve_d(payload), result)

    def test_resume_accepts_one_frozen_pending_plus_one_effective_terminal(self) -> None:
        pending = {"resolution": "PENDING_APPLICABILITY"}
        terminal = {"resolution": "NOT_APPLICABLE"}
        with mock.patch.object(runtime, "_assert_resume_order"), mock.patch.object(
            runtime, "load_enhanced_d_lock", return_value={}
        ), mock.patch.object(
            runtime, "_application_state", return_value=([pending], [terminal])
        ), mock.patch.object(
            runtime,
            "patched_legacy_workspace_path",
            return_value=nullcontext(),
        ), mock.patch.object(runtime.recovery, "load_lock", return_value={"recovery": 1}), mock.patch.object(
            runtime.recovery, "resume_preflight", return_value={"status": "PASS"}
        ) as call:
            self.assertEqual(runtime.resume_preflight({}, 58), {"status": "PASS"})
            call.assert_called_once_with({"recovery": 1}, 58)

    def test_manifest_overlay_binds_correction_lock_and_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "input_hash_manifest.sha256"

            def writer(path: Path, files: list[Path]) -> None:
                path.write_text(
                    "".join(f"hash  {audit_path}\n" for audit_path in map(runtime.audit_v3.display_path, files)),
                    encoding="utf-8",
                )

            with mock.patch.object(runtime.recovery.base_job, "write_hash_manifest", writer):
                with runtime.correction_manifest_overlay():
                    runtime.recovery.base_job.write_hash_manifest(manifest, [])
            text = manifest.read_text(encoding="utf-8")
            self.assertIn(runtime.audit_v3.display_path(runtime.LOCK_PATH), text)
            self.assertIn(runtime.audit_v3.display_path(runtime.WRAPPER_PATH), text)


if __name__ == "__main__":
    unittest.main()
