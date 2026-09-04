from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2


class PostIncidentVerifierV2Tests(unittest.TestCase):
    def _write_compact(self, path: Path, value: object) -> None:
        path.write_bytes(v2.shared_exporter.canonical_json_bytes(value))

    def test_exact_two_authorized_labels_use_real_producer_codec(self) -> None:
        self.assertEqual(
            v2.STRICT_SHARED_PRODUCER_LABELS,
            frozenset({"SHARED_MANIFEST_SOURCE_CHAIN", "SHARED_MANIFEST"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            value = {"schema_version": "synthetic", "status": "PASS", "z": 1}
            self._write_compact(path, value)
            for label in sorted(v2.STRICT_SHARED_PRODUCER_LABELS):
                observed, _identity = v2.load_canonical_json_v2(path, label)
                self.assertEqual(observed, value)

    def test_producer_codec_helper_rejects_unauthorized_third_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            self._write_compact(path, {"status": "PASS"})
            with self.assertRaisesRegex(
                v1.VerificationError, "V2_SHARED_CODEC_UNAUTHORIZED_LABEL"
            ):
                v2._producer_canonical_json(path, "B1_GUARD_DECISION")

    def test_shared_labels_reject_pretty_whitespace_and_noncanonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            value = {"schema_version": "synthetic", "status": "PASS", "z": 1}
            payloads = (
                v1.canonical_json(value),
                v2.shared_exporter.canonical_json_bytes(value) + b" ",
                b'{"z":1,"status":"PASS","schema_version":"synthetic"}\n',
            )
            for payload in payloads:
                path.write_bytes(payload)
                with self.assertRaisesRegex(
                    v1.VerificationError, "NOT_PRODUCER_CANONICAL_OBJECT"
                ):
                    v2.load_canonical_json_v2(path, "SHARED_MANIFEST")

    def test_semantic_tamper_still_fails_v1_shared_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "schema_version": "tampered-schema",
                "status": v1.SHARED_STATUS,
            }
            self._write_compact(root / "conversion_manifest.json", manifest)
            prior = v1.load_canonical_json
            v1.load_canonical_json = v2.load_canonical_json_v2
            try:
                with self.assertRaisesRegex(
                    v1.VerificationError, "SHARED_MANIFEST_SCHEMA_OR_STATUS_MISMATCH"
                ):
                    v1.validate_reference(root)
            finally:
                v1.load_canonical_json = prior

    def test_compact_shared_manifest_passes_full_reference_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            mapping = []
            source_rows = []
            poses = []
            for offset, global_index in enumerate(range(5400, 6301, 20)):
                stamp = v1.SCORE_FIRST_NS + offset * 1_000_000_000
                if offset == 45:
                    stamp = v1.SCORE_LAST_NS
                mapping.append(
                    {"global_camera_index": global_index, "header_ns": stamp}
                )
                source_rows.append(f"{global_index} 0 0 0 0 0 0 1")
                poses.append(
                    v1.shared_exporter.ReferencePose(
                        global_camera_index=global_index,
                        header_ns=stamp,
                        position_xyz=(0.0, 0.0, 0.0),
                        quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
                    )
                )
            source = root / "source_gt.txt"
            source.write_text("\n".join(source_rows) + "\n", encoding="ascii")
            (shared / "reference_proxy.tum").write_bytes(
                v1.shared_exporter.reference_tum_bytes(tuple(poses))
            )
            manifest = {
                "reference": {
                    "identity": {
                        "path": str(source.resolve(strict=True)),
                        "sha256": v1.sha256_bytes(source.read_bytes()),
                        "size_bytes": source.stat().st_size,
                    },
                    "mapping": mapping,
                    "pose_convention": "world_T_camera",
                    "target_rows": 46,
                },
                "schema_version": v1.SHARED_SCHEMA,
                "status": v1.SHARED_STATUS,
                "views": {"reference_tum": "shared/reference_proxy.tum"},
                "window": {
                    "score_reference_count": 46,
                    "score_reference_global_indices": list(range(5400, 6301, 20)),
                },
            }
            self._write_compact(root / "conversion_manifest.json", manifest)
            prior = v1.load_canonical_json
            v1.load_canonical_json = v2.load_canonical_json_v2
            try:
                reference, manifest_identity = v1.validate_reference(root)
                self.assertEqual(
                    reference["path"],
                    str((shared / "reference_proxy.tum").resolve(strict=True)),
                )
                self.assertEqual(
                    manifest_identity["sha256"],
                    v1.sha256_bytes((root / "conversion_manifest.json").read_bytes()),
                )
            finally:
                v1.load_canonical_json = prior

    def test_compact_shared_source_chain_binds_current_provenance_and_bag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window = root / "window.bag"
            window_manifest = root / "window.bag.manifest.json"
            window.write_bytes(b"bag")
            window_manifest.write_bytes(b"manifest")
            derived = {
                "path": str(window.resolve(strict=True)),
                "size_bytes": 3,
                "sha256": v1.sha256_bytes(b"bag"),
            }
            provenance = {
                "derived_window_bag": derived,
                "output_topic_counts": {"/camera/image_raw": 1801},
                "path": str(window_manifest.resolve(strict=True)),
                "producer_record": {
                    "output": {},
                    "provenance": {"converter": {}, "gt": {}, "raw_tar": {}},
                },
                "sha256": v1.sha256_bytes(b"manifest"),
                "size_bytes": 8,
            }
            shared_manifest = {
                "source": {
                    "derived_window_bag": derived,
                    "provenance": provenance,
                }
            }
            manifest_path = root / "conversion_manifest.json"
            self._write_compact(manifest_path, shared_manifest)
            prior = v1.load_canonical_json
            v1.load_canonical_json = v2.load_canonical_json_v2
            try:
                with mock.patch.object(
                    v1.shared_exporter, "validate_provenance", return_value=provenance
                ):
                    report = v1.validate_shared_source_chain(
                        root, window, window_manifest
                    )
                    self.assertEqual(report["canonical_window_bag_identity"], derived)
                    shared_manifest["source"]["derived_window_bag"] = {
                        **derived,
                        "sha256": "0" * 64,
                    }
                    self._write_compact(manifest_path, shared_manifest)
                    with self.assertRaisesRegex(
                        v1.VerificationError, "DERIVED_WINDOW_IDENTITY_MISMATCH"
                    ):
                        v1.validate_shared_source_chain(root, window, window_manifest)
                    shared_manifest["source"]["derived_window_bag"] = derived
                    shared_manifest["source"]["provenance"] = {
                        **provenance,
                        "sha256": "f" * 64,
                    }
                    self._write_compact(manifest_path, shared_manifest)
                    with self.assertRaisesRegex(
                        v1.VerificationError,
                        "SHARED_SOURCE_PROVENANCE_NOT_CURRENT_CANONICAL_WINDOW",
                    ):
                        v1.validate_shared_source_chain(root, window, window_manifest)
            finally:
                v1.load_canonical_json = prior

    def test_every_other_label_retains_v1_pretty_codec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "other.json"
            value = {"schema_version": "synthetic", "status": "PASS"}
            path.write_bytes(v1.canonical_json(value))
            observed, _identity = v2.load_canonical_json_v2(path, "B1_GUARD_DECISION")
            self.assertEqual(observed, value)
            self._write_compact(path, value)
            with self.assertRaisesRegex(v1.VerificationError, "NOT_CANONICAL_OBJECT"):
                v2.load_canonical_json_v2(path, "B1_GUARD_DECISION")

    def test_delegate_installs_narrow_loader_and_restores_on_failure(self) -> None:
        original = v1.load_canonical_json

        def failing_main(_argv: object) -> int:
            self.assertIs(v1.load_canonical_json, v2.load_canonical_json_v2)
            raise RuntimeError("synthetic")

        def binding(_path: Path, *, evidence_stage: str) -> dict[str, object]:
            return {"evidence_stage": evidence_stage}

        with mock.patch.object(v1, "main", side_effect=failing_main), mock.patch.object(
            v2, "continuation_provenance_binding", side_effect=binding
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                v2._delegate_to_v1(
                    ["--action", "check-static"], Path("/tmp/revision.json")
                )
        self.assertIs(v1.load_canonical_json, original)

    def test_inventory_is_sorted_complete_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "tree"
            (root / "b").mkdir(parents=True)
            (root / "a.txt").write_bytes(b"a")
            (root / "b/z.txt").write_bytes(b"z")
            first = v2.inventory_tree(root, "SYNTHETIC")
            self.assertEqual(
                [entry["relative_path"] for entry in first],
                [".", "a.txt", "b", "b/z.txt"],
            )
            self.assertEqual(v2._inventory_summary(first)["regular_file_count"], 2)
            (root / "b/z.txt").write_bytes(b"changed")
            second = v2.inventory_tree(root, "SYNTHETIC")
            self.assertNotEqual(first, second)
            self.assertNotEqual(
                v2._inventory_summary(first)["inventory_sha256"],
                v2._inventory_summary(second)["inventory_sha256"],
            )

    def test_inventory_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "tree"
            root.mkdir()
            target = root / "target"
            target.write_bytes(b"x")
            (root / "link").symlink_to(target)
            with self.assertRaisesRegex(v1.VerificationError, "NOT_REGULAR_NONSYMLINK"):
                v2.inventory_tree(root, "SYNTHETIC")

    def test_camera_pair_gate_requires_real_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "shared/cam0/data"
            right = root / "hfnet/mav0/cam0/data"
            left.mkdir(parents=True)
            right.mkdir(parents=True)
            for name in ("1.png", "2.png"):
                source = left / name
                source.write_bytes(name.encode("ascii"))
                os.link(source, right / name)
            with mock.patch.object(v2, "EXPECTED_SHARED_HARDLINK_PAIR_COUNT", 2):
                self.assertEqual(v2.validate_shared_hardlinks(root)["pair_count"], 2)
                (right / "2.png").unlink()
                (right / "2.png").write_bytes(b"2.png")
                with self.assertRaisesRegex(v1.VerificationError, "NOT_HARDLINK_PAIR"):
                    v2.validate_shared_hardlinks(root)

    def test_continuation_commands_start_at_9r_and_never_retry_consumed_steps(self) -> None:
        old = json.loads(v2.DEFAULT_OLD_FREEZE.read_text(encoding="utf-8"))
        commands = v2.expected_continuation_commands(old)
        self.assertEqual(len(commands), 19)
        self.assertIn(
            "build_a02_long_post_incident_continuation_freeze_v2.py --action check",
            commands[0],
        )
        self.assertIn("--action check-continuation-start", commands[0])
        self.assertIn("--action check-b1-decision", commands[0])
        self.assertTrue(commands[0].endswith("|| exit 42"))
        joined = "\n".join(commands)
        self.assertNotIn("verify_a02_long_three_arm_eval_inputs_v1.py", joined)
        self.assertNotIn("materialize_aqualoc_a02_4500_6300_window_v1.py", joined)
        self.assertNotIn("export_aqualoc_a02_shared_4500_6300_v1.py", joined)
        self.assertNotIn("run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh", joined)
        self.assertNotIn(str(v1.DEFAULT_OUTPUT), joined)
        self.assertNotIn(str(v1.DEFAULT_POST_EVAL_OUTPUT), joined)
        self.assertIn(str(v2.DEFAULT_V2_EVIDENCE), joined)
        self.assertIn(str(v2.DEFAULT_V2_POST_EVAL_EVIDENCE), joined)
        self.assertEqual(
            commands[1],
            old["commands"][10].replace(
                "scripts/verify_a02_long_three_arm_eval_inputs_v1.py",
                "scripts/verify_a02_long_three_arm_eval_inputs_v2.py"
                f" --revision-freeze {v2.DEFAULT_REVISION_FREEZE}",
            ),
        )

    def test_revision_option_is_removed_before_v1_parser(self) -> None:
        filtered, revision = v2._split_revision_argument(
            [
                "--revision-freeze",
                "/tmp/freeze.json",
                "--action",
                "check-b1-decision",
            ]
        )
        self.assertEqual(filtered, ["--action", "check-b1-decision"])
        self.assertEqual(revision, Path("/tmp/freeze.json"))

    def test_committed_freeze_is_canonical_and_binds_full_carry_forward(self) -> None:
        payload = v2.DEFAULT_REVISION_FREEZE.read_bytes()
        freeze = json.loads(payload.decode("utf-8"))
        self.assertEqual(payload, v1.canonical_json(freeze))
        self.assertEqual(freeze["schema_version"], v2.SCHEMA)
        self.assertEqual(freeze["status"], v2.STATUS)
        self.assertEqual(len(freeze["commands"]), 19)
        self.assertEqual(len(freeze["consumed_old_reserved_paths"]), 5)
        self.assertEqual(len(freeze["remaining_reserved_paths"]), 13)
        self.assertEqual(len(freeze["redirected_continuation_reserved_paths"]), 13)
        self.assertEqual(
            freeze["evidence_contracts"]["pre_eval_schema"],
            v2.PRE_EVAL_SCHEMA_V2,
        )
        self.assertEqual(
            freeze["evidence_contracts"]["post_eval_schema"],
            v2.POST_EVAL_SCHEMA_V2,
        )
        shared = freeze["carry_forward"]["shared_root"]
        self.assertEqual(shared["summary"]["directory_count"], 9)
        self.assertEqual(shared["summary"]["regular_file_count"], 3609)
        self.assertEqual(len(shared["entries"]), 3618)
        self.assertEqual(shared["camera_hardlinks"]["pair_count"], 1801)
        self.assertEqual(
            freeze["old_protocol"]["status"],
            "TERMINATED_AT_COMMAND9_NOT_RESUMED_NOT_FULFILLED",
        )
        self.assertEqual(
            freeze["runtime_boundary"]["python_pycache_prefix"],
            str(v2.EMPTY_PYCACHE_PREFIX),
        )
        for label, path in {
            "v2_verifier": v2.V2_VERIFIER,
            "v2_tests": Path(__file__).resolve(),
        }.items():
            claim = freeze["required_static_identities"][label]
            self.assertEqual(v2._identity(path, f"TEST_{label}"), claim)

    def test_consumed_identity_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consumed.bin"
            path.write_bytes(b"frozen")
            claim = {
                "path": str(path.resolve(strict=True)),
                "sha256": v1.sha256_bytes(b"frozen"),
                "size_bytes": 6,
            }
            self.assertEqual(v2._require_identity(claim, "CONSUMED"), claim)
            path.write_bytes(b"drifted")
            with self.assertRaisesRegex(v1.VerificationError, "IDENTITY_MISMATCH"):
                v2._require_identity(claim, "CONSUMED")

    def test_reserved_partition_rejects_missing_consumed_and_early_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            consumed = [root / f"consumed_{index}" for index in range(5)]
            remaining = [root / f"remaining_{index}" for index in range(13)]
            for path in consumed:
                path.write_bytes(b"x")
            old = {
                "reserved_paths_absent_at_freeze": [
                    *[str(path) for path in consumed],
                    *[str(path) for path in remaining],
                ]
            }
            revision = {
                "consumed_old_reserved_paths": [str(path) for path in consumed],
                "remaining_reserved_paths": [str(path) for path in remaining],
                "redirected_continuation_reserved_paths": [
                    str(path) for path in remaining
                ],
            }
            report = v2.validate_reserved_partition(
                revision, old, require_remaining_absent=True
            )
            self.assertEqual(report["consumed_count"], 5)
            consumed[3].unlink()
            with self.assertRaisesRegex(v1.VerificationError, "CONSUMED_PATH_MISSING"):
                v2.validate_reserved_partition(
                    revision, old, require_remaining_absent=True
                )
            consumed[3].write_bytes(b"x")
            remaining[7].write_bytes(b"premature")
            with self.assertRaisesRegex(
                v1.VerificationError, "REMAINING_RESERVED_PATH_NOT_ABSENT"
            ):
                v2.validate_reserved_partition(
                    revision, old, require_remaining_absent=True
                )

    def test_pre_and_post_seal_check_recompute_continuation_provenance(self) -> None:
        stores: dict[str, bytes] = {}

        def binding(_path: Path, *, evidence_stage: str) -> dict[str, object]:
            return {
                "continuation_freeze": {"sha256": "a" * 64},
                "evidence_stage": evidence_stage,
                "incident_receipt": {"sha256": "b" * 64},
                "old_protocol_terminated": True,
                "role": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
                "v2_verifier": {"sha256": "c" * 64},
            }

        def fake_main(argv: object) -> int:
            args = list(argv)
            action = args[args.index("--action") + 1]
            post = action in {"seal-evaluation", "check-evaluation"}
            record = (
                v1.build_post_eval_record(None) if post else v1.build_record(None)
            )
            expected_schema = v2.POST_EVAL_SCHEMA_V2 if post else v2.PRE_EVAL_SCHEMA_V2
            self.assertEqual(record["schema_version"], expected_schema)
            self.assertEqual(
                record["post_incident_continuation"]["evidence_stage"],
                "post_eval" if post else "pre_eval",
            )
            key = "post" if post else "pre"
            encoded = v1.canonical_json(record)
            if action.startswith("seal"):
                stores[key] = encoded
                return 0
            return 0 if stores.get(key) == encoded else 2

        with mock.patch.object(
            v2, "continuation_provenance_binding", side_effect=binding
        ), mock.patch.object(
            v2,
            "_ORIGINAL_V1_BUILD_RECORD",
            return_value={"schema_version": v1.SCHEMA, "status": v1.STATUS},
        ), mock.patch.object(
            v2,
            "_ORIGINAL_V1_BUILD_POST_EVAL_RECORD",
            return_value={
                "schema_version": v1.POST_EVAL_SCHEMA,
                "status": v1.POST_EVAL_STATUS,
            },
        ), mock.patch.object(v1, "main", side_effect=fake_main):
            revision = Path("/tmp/revision.json")
            self.assertEqual(v2._delegate_to_v1(["--action", "seal"], revision), 0)
            self.assertEqual(v2._delegate_to_v1(["--action", "check"], revision), 0)
            self.assertEqual(
                v2._delegate_to_v1(["--action", "seal-evaluation"], revision), 0
            )
            self.assertEqual(
                v2._delegate_to_v1(["--action", "check-evaluation"], revision), 0
            )
            stores["pre"] = stores["pre"].replace(b"REVISED", b"TAMPERED", 1)
            stores["post"] = stores["post"].replace(b"REVISED", b"TAMPERED", 1)
            self.assertEqual(v2._delegate_to_v1(["--action", "check"], revision), 2)
            self.assertEqual(
                v2._delegate_to_v1(["--action", "check-evaluation"], revision), 2
            )

    def test_injected_provenance_rejects_duplicate_or_wrong_stage(self) -> None:
        binding = {"evidence_stage": "pre_eval"}
        result = v2.inject_continuation_provenance(
            {"schema_version": "v1"}, binding, evidence_stage="pre_eval"
        )
        self.assertEqual(result["schema_version"], v2.PRE_EVAL_SCHEMA_V2)
        with self.assertRaisesRegex(v1.VerificationError, "ALREADY_PRESENT"):
            v2.inject_continuation_provenance(
                result, binding, evidence_stage="pre_eval"
            )
        with self.assertRaisesRegex(v1.VerificationError, "STAGE_MISMATCH"):
            v2.inject_continuation_provenance(
                {"schema_version": "v1"}, binding, evidence_stage="post_eval"
            )

    def test_every_machine_authority_field_is_fail_closed(self) -> None:
        old = {"path": "/old", "sha256": "a" * 64, "size_bytes": 1}
        incident = {"path": "/incident", "sha256": "b" * 64, "size_bytes": 2}
        diagnosis = {
            "actual_identity": {
                "path": "/manifest",
                "sha256": "c" * 64,
                "size_bytes": 3,
            },
            "actual_is_producer_compact_canonical": True,
            "actual_is_v1_pretty_canonical": False,
            "producer_compact_sha256": "c" * 64,
            "v1_pretty_reencoding_sha256": "d" * 64,
        }
        expected = v2.expected_authority_fields(old, incident, diagnosis)
        v2.validate_authority_fields(dict(expected), expected)
        for key in expected:
            tampered = dict(expected)
            tampered[key] = "TAMPERED"
            with self.assertRaisesRegex(
                v1.VerificationError,
                f"CONTINUATION_MACHINE_AUTHORITY_FIELD_MISMATCH:{key}",
            ):
                v2.validate_authority_fields(tampered, expected)


if __name__ == "__main__":
    unittest.main()
