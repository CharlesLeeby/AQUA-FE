from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from unittest import mock

from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_correction
from scripts import build_p07_backend_replay_queue_v1 as builder
from scripts import p07_backend_replay_common_v1 as replay_common
from scripts import validate_p07_backend_replay_queue_v1 as validator


HASHES = tuple(hashlib.sha256(f"hash-{index}".encode()).hexdigest() for index in range(8))
PATTERNS = (
    (builder.B0, builder.B1, builder.M_ARM, builder.P_ARM),
    (builder.B1, builder.P_ARM, builder.B0, builder.M_ARM),
    (builder.P_ARM, builder.M_ARM, builder.B1, builder.B0),
    (builder.M_ARM, builder.B0, builder.P_ARM, builder.B1),
)


def fixture_snapshot(*, applicable_windows: int = 1) -> builder.ReadinessSnapshot:
    manifest: list[dict[str, str]] = []
    arm_order: list[dict[str, str]] = []
    sources: dict[tuple[str, str], builder.SourceEvidence] = {}
    resolutions: dict[str, builder.DResolution] = {}
    queue_index = 0
    for index in range(20):
        rank = index + 1
        window_id = f"ntnu:fixture_{rank:02d}:0000"
        manifest.append(
            {
                "window_id": window_id,
                "dataset_family": "ntnu",
                "data_domain": "fixture",
                "sequence": f"fixture_{rank:02d}",
                "window_start_s": str(index * 45),
                "window_end_s": str((index + 1) * 45),
                "texture_stratum": "low" if index < 10 else "normal",
                "selection_tier": (
                    "RELATIVE_Q80_FALLBACK" if index < 10 else "STRICT_NORMAL"
                ),
            }
        )
        pattern = PATTERNS[index % len(PATTERNS)]
        for position, arm in enumerate((*pattern, builder.D_ARM), 1):
            arm_order.append(
                {
                    "window_id": window_id,
                    "assignment_rank": str(rank),
                    "pattern_id": str(index % len(PATTERNS)),
                    "order_position": str(position),
                    "arm": arm,
                    "arm_role": f"fixture_{arm}",
                }
            )
        for arm in builder.FEATURE_ARMS:
            queue_index += 1
            token = hashlib.sha256(f"{window_id}:{arm}".encode()).hexdigest()
            source_provenance = {
                "schema_version": "fixture-frontend-provenance-v1",
                "kind": "CANONICAL_FRONTEND_COMPLETED_V1",
                "source_run_id": f"frontend-run-{queue_index}",
                "window_id": window_id,
                "arm": arm,
                "held_out_trajectory_outcome_read": False,
            }
            sources[(window_id, arm)] = builder.SourceEvidence(
                window_id=window_id,
                arm=arm,
                frontend_queue_index=queue_index,
                d_slot_index=None,
                feature_bag=f"fixtures/{token}.bag",
                feature_bag_sha256=token,
                feature_bag_size_bytes=8 * 1024 * 1024,
                attestation_path=f"fixtures/{token}.attestation.json",
                attestation_sha256=hashlib.sha256(f"att:{token}".encode()).hexdigest(),
                input_audit_path=f"fixtures/{token}.audit.json",
                input_audit_sha256=hashlib.sha256(f"audit:{token}".encode()).hexdigest(),
                source_run_id=f"frontend-run-{queue_index}",
                source_provenance_kind="CANONICAL_FRONTEND_COMPLETED_V1",
                source_provenance_hash=builder.frontend_provenance.provenance_hash(
                    source_provenance
                ),
                source_provenance=source_provenance,
            )
        applicable = index < applicable_windows
        d_source = None
        resolution_provenance = {
            "schema_version": "fixture-d-resolution-provenance-v1",
            "kind": "FIXTURE_D_RESOLUTION_V1",
            "window_id": window_id,
            "slot_index": rank,
            "resolution": "APPLICABLE" if applicable else "NOT_APPLICABLE",
            "held_out_trajectory_outcome_read": False,
        }
        if applicable:
            token = hashlib.sha256(f"{window_id}:D".encode()).hexdigest()
            d_provenance = {
                **resolution_provenance,
                "kind": builder.D_PROVENANCE_KIND,
                "source_run_id": f"parent-p-run-{rank}",
            }
            d_source = builder.SourceEvidence(
                window_id=window_id,
                arm=builder.D_ARM,
                frontend_queue_index=None,
                d_slot_index=rank,
                feature_bag=f"fixtures/{token}.bag",
                feature_bag_sha256=token,
                feature_bag_size_bytes=7 * 1024 * 1024,
                attestation_path=f"fixtures/{token}.attestation.json",
                attestation_sha256=hashlib.sha256(f"att:{token}".encode()).hexdigest(),
                input_audit_path=f"fixtures/{token}.exact-drop.json",
                input_audit_sha256=hashlib.sha256(f"audit:{token}".encode()).hexdigest(),
                source_run_id=f"parent-p-run-{rank}",
                source_provenance_kind=builder.D_PROVENANCE_KIND,
                source_provenance_hash=builder.frontend_provenance.provenance_hash(
                    d_provenance
                ),
                source_provenance=d_provenance,
            )
            sources[(window_id, builder.D_ARM)] = d_source
        resolutions[window_id] = builder.DResolution(
            window_id=window_id,
            slot_index=rank,
            resolution="APPLICABLE" if applicable else "NOT_APPLICABLE",
            evidence_path=f"fixtures/{rank:02d}.d-resolution.json",
            evidence_sha256=hashlib.sha256(f"d:{rank}".encode()).hexdigest(),
            resolution_provenance_hash=builder.frontend_provenance.provenance_hash(
                resolution_provenance
            ),
            resolution_provenance=resolution_provenance,
            source=d_source,
        )
    return builder.ReadinessSnapshot(
        manifest_rows=tuple(manifest),
        arm_order_rows=tuple(arm_order),
        sources=sources,
        d_resolutions=resolutions,
        frontend_completed=60,
        frontend_total=60,
        frontend_audit_pass=60,
        d_terminal=20,
        d_total=20,
    )


class P07BackendReplayQueueV1Tests(unittest.TestCase):
    @staticmethod
    def _general_d_fixture() -> tuple[
        dict[str, object], dict[str, object], dict[str, str], list[str], Path
    ]:
        p_audit = "papers/p07/p-audit.json"
        p_bag = "logs/p/features.bag"
        b1_bag = "logs/b1/features.bag"
        common_paths = {
            builder.display_path(builder.FRONTEND_QUEUE),
            builder.display_path(builder.FRONTEND_ALLOCATION),
            builder.display_path(builder.FRONTEND_QUEUE_LOCK),
            builder.display_path(builder.METHOD_LOCK),
            builder.display_path(builder.D_QUEUE),
            p_audit,
            p_bag,
            b1_bag,
            "scripts/resolve_p07_d_applicability_v2.py",
            "scripts/build_p07_d_resolution_lock_v2.py",
            "scripts/filter_feature_bag_by_channel.py",
            "scripts/audit_whole_lineage_exact_drop_v1.py",
            "scripts/attest_nativeq_feature_bag.py",
            "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json",
        }
        artifact_hash = "a" * 64
        artifacts = [
            {"path": path, "sha256": artifact_hash, "size_bytes": 1}
            for path in sorted(common_paths)
        ]
        prefixes = [
            {
                "path": builder.display_path(path),
                "sha256": "b" * 64,
                "size_bytes": 1,
            }
            for path in (builder.ARM_APPLICABILITY, builder.RUN_REGISTRY)
        ]
        evidence_path = builder.ROOT / "papers/p07/d-resolution.json"
        lock: dict[str, object] = {
            "schema_version": "isj-p07-d-resolution-lock-v2",
            "status": "FROZEN_READY_TO_RESOLVE_D",
            "frozen_at": "2026-08-08T00:00:00+08:00",
            "window_id": "ntnu:fixture:0001",
            "dataset_family": "ntnu",
            "sequence": "fixture",
            "lineage_contract": {
                "accepted_learned_born_lineage_count": 0,
                "birth_rule": "first ID occurrence has is_learned=1 or source_code in {10,20,30}",
                "late_marker_policy": "FAIL_CLOSED",
            },
            "decision": "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1",
            "parent_p": {
                "run_id": "p-run",
                "registry_event_id": "p-e02",
                "audit": p_audit,
                "feature_bag": p_bag,
                "feature_bag_sha256": artifact_hash,
            },
            "b1": {
                "run_id": "b1-run",
                "registry_event_id": "b1-e02",
                "feature_bag": b1_bag,
                "feature_bag_sha256": artifact_hash,
            },
            "expected_resolution_output": builder.display_path(evidence_path),
            "expected_derivation_dir": None,
            "artifacts": artifacts,
            "mutable_stream_prefix_snapshots": prefixes,
            "outcome_boundary": "FRONTEND_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
            "trajectory_outcome_read": False,
        }
        lock["resolution_lock_hash"] = builder.frontend_provenance.document_hash(
            lock, "resolution_lock_hash"
        )
        fields = ["accepted_lineage_count", "resolution", "resolver_hash"]
        row = {
            "accepted_lineage_count": "0",
            "resolution": "NOT_APPLICABLE",
            "resolver_hash": str(lock["resolution_lock_hash"]),
        }
        rendered = builder.sha256_bytes(
            builder._render_applicability_row(fields, row)
        )
        evidence: dict[str, object] = {
            "resolution_lock": "papers/p07/d-lock.json",
            "resolver_hash": lock["resolution_lock_hash"],
            "window_id": lock["window_id"],
            "resolution": "NOT_APPLICABLE",
            "accepted_learned_born_lineage_count": 0,
            "parent_p_run_id": "p-run",
            "p_audit": p_audit,
            "p_audit_sha256": artifact_hash,
            "derivation": None,
            "zero_action_identity": {
                "status": "PASS_BYTE_IDENTICAL_TO_B1",
                "p_feature_bag": p_bag,
                "p_feature_bag_sha256": artifact_hash,
                "b1_feature_bag": b1_bag,
                "b1_feature_bag_sha256": artifact_hash,
            },
            "canonical_stream": {
                "path": builder.display_path(builder.ARM_APPLICABILITY),
                "appended_row_sha256": rendered,
                "prefix_sha256": "b" * 64,
                "prefix_size_bytes": 1,
            },
        }
        return lock, evidence, row, fields, evidence_path

    def test_general_d_lock_rejects_rehashed_empty_evidence_and_applicable_switch(self) -> None:
        lock, evidence, row, fields, evidence_path = self._general_d_fixture()

        def checked(record: dict[str, object], *, label: str) -> builder.FileRecord:
            del label
            return builder.FileRecord(
                str(record["path"]), str(record["sha256"]), int(record["size_bytes"])
            )

        def run(candidate: dict[str, object], candidate_evidence: dict[str, object], candidate_row: dict[str, str]) -> None:
            with mock.patch.object(
                builder,
                "json_snapshot",
                return_value=(candidate, builder.FileRecord("papers/p07/d-lock.json", "c" * 64, 1)),
            ), mock.patch.object(
                builder, "_checked_file_from_payload", side_effect=checked
            ), mock.patch.object(builder, "_validate_prefix_snapshot"):
                builder._validate_general_d_lock(
                    window={"window_id": "ntnu:fixture:0001"},
                    evidence_path=evidence_path,
                    evidence_payload=candidate_evidence,
                    canonical_row=candidate_row,
                    applicability_fields=fields,
                )

        run(lock, evidence, row)
        for key in ("artifacts", "mutable_stream_prefix_snapshots"):
            altered = json.loads(json.dumps(lock))
            altered[key] = []
            altered["resolution_lock_hash"] = builder.frontend_provenance.document_hash(
                altered, "resolution_lock_hash"
            )
            altered_evidence = json.loads(json.dumps(evidence))
            altered_evidence["resolver_hash"] = altered["resolution_lock_hash"]
            altered_row = dict(row, resolver_hash=str(altered["resolution_lock_hash"]))
            with self.assertRaisesRegex(builder.ReadinessError, "artifact set|prefix"):
                run(altered, altered_evidence, altered_row)

        altered = json.loads(json.dumps(lock))
        altered["lineage_contract"]["accepted_learned_born_lineage_count"] = 1
        altered["decision"] = "APPLICABLE_DERIVE_EXACT_WHOLE_LINEAGE_DROP"
        altered["expected_derivation_dir"] = "papers/p07/derived"
        altered["resolution_lock_hash"] = builder.frontend_provenance.document_hash(
            altered, "resolution_lock_hash"
        )
        altered_evidence = json.loads(json.dumps(evidence))
        altered_evidence["resolver_hash"] = altered["resolution_lock_hash"]
        altered_row = dict(row, resolver_hash=str(altered["resolution_lock_hash"]))
        with self.assertRaisesRegex(builder.ReadinessError, "decision/lineage"):
            run(altered, altered_evidence, altered_row)

    def test_json_snapshot_rejects_leaf_symlink_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.json"
            outside.write_text('{"status":"PASS"}\n', encoding="utf-8")
            leaf = root / "papers/evidence.json"
            leaf.parent.mkdir(parents=True)
            leaf.symlink_to(outside)
            with mock.patch.object(builder, "ROOT", root), mock.patch.dict(
                builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS, {}, clear=True
            ):
                with self.assertRaises(builder.ReadinessError):
                    builder.json_snapshot(leaf, label="synthetic queue evidence")
                leaf.unlink()
                os.link(outside, leaf)
                with self.assertRaises(builder.ReadinessError):
                    builder.json_snapshot(leaf, label="synthetic queue evidence")

    def test_additive_epoch_correction_is_the_authorized_bundle(self) -> None:
        payload = epoch_correction.build_lock(
            root=epoch_correction.ROOT,
            frozen_at="2026-08-08T12:00:00+08:00",
        )
        self.assertEqual(
            builder.evaluator_implementation_hash(payload),
            payload["corrected_implementation_binding"][
                "implementation_bundle_sha256"
            ],
        )

    def test_queue_is_240_plus_three_per_applicable_d(self) -> None:
        rows = builder.build_queue_rows(
            fixture_snapshot(applicable_windows=2),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        self.assertEqual(len(rows), 246)
        counts = Counter(row["arm"] for row in rows)
        self.assertEqual(
            {arm: counts[arm] for arm in builder.REQUIRED_ARMS},
            {arm: 60 for arm in builder.REQUIRED_ARMS},
        )
        self.assertEqual(counts[builder.D_ARM], 6)
        self.assertTrue(all(row["status"] == "PLANNED" for row in rows))

    def test_williams_order_and_repeats_are_serial(self) -> None:
        rows = builder.build_queue_rows(
            fixture_snapshot(),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        by_window: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            by_window[str(row["window_id"])].append(row)
        for index, (_window_id, window_rows) in enumerate(by_window.items()):
            arm_groups: list[str] = []
            slots: dict[str, list[int]] = defaultdict(list)
            for row in window_rows:
                arm = str(row["arm"])
                if not arm_groups or arm_groups[-1] != arm:
                    arm_groups.append(arm)
                slots[arm].append(int(row["replay_index"]))
            expected = list(PATTERNS[index % 4])
            if index == 0:
                expected.append(builder.D_ARM)
            self.assertEqual(arm_groups, expected)
            self.assertTrue(all(values == [1, 2, 3] for values in slots.values()))

    def test_b0_is_native_and_feature_arms_are_immutable_overrides(self) -> None:
        rows = builder.build_queue_rows(
            fixture_snapshot(),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        for row in rows:
            argv = json.loads(str(row["replay_argv_json"]))
            self.assertEqual(argv[0:2], ["python3", "scripts/run_p07_backend_replay_job_v1.py"])
            self.assertNotIn("bash", argv)
            self.assertEqual(row["runner_every_n"], 2)
            if row["arm"] == builder.B0:
                self.assertEqual(row["runner_mode"], "origin")
                self.assertEqual(row["runner_method"], "klt")
                self.assertEqual(row["feature_bag"], "")
                self.assertEqual(row["attestation_path"], "")
            else:
                self.assertEqual(row["runner_mode"], "external")
                self.assertTrue(row["feature_bag"])
                self.assertTrue(row["attestation_path"])
                expected_method = "xfeat" if row["arm"] == builder.M_ARM else "klt"
                self.assertEqual(row["runner_method"], expected_method)
            expected_dir = (
                f"logs/ntnu_vins/{row['runner_mode']}_{row['runner_method']}_"
                f"every2_{row['runner_tag']}"
            )
            self.assertEqual(row["expected_run_dir"], expected_dir)

    def test_every_built_row_passes_the_runtime_common_contract(self) -> None:
        rows = builder.build_queue_rows(
            fixture_snapshot(),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
        )
        for row in rows:
            replay_common.validate_queue_row(
                {field: str(value) for field, value in row.items()}
            )

    def test_formal_readiness_requires_60_of_60_and_20_of_20(self) -> None:
        snapshot = fixture_snapshot()
        builder.assert_ready(snapshot)
        with self.assertRaisesRegex(builder.ReadinessError, "60/60"):
            builder.assert_ready(replace(snapshot, frontend_completed=59))
        with self.assertRaisesRegex(builder.ReadinessError, "20/20"):
            builder.assert_ready(replace(snapshot, d_terminal=19))
        missing = dict(snapshot.sources)
        missing.pop((snapshot.manifest_rows[0]["window_id"], builder.P_ARM))
        with self.assertRaisesRegex(builder.ReadinessError, "missing frozen frontend source"):
            builder.assert_ready(replace(snapshot, sources=missing))

    def test_queue_lock_allocation_and_validator_are_consistent(self) -> None:
        snapshot = fixture_snapshot(applicable_windows=1)
        outputs = builder.build_outputs(
            snapshot,
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
            include_code_records=False,
        )
        lock = json.loads(outputs[builder.BACKEND_QUEUE_LOCK])
        issues = validator.validate_artifacts(
            queue_content=outputs[builder.BACKEND_QUEUE],
            allocation_content=outputs[builder.BACKEND_ALLOCATION],
            lock_payload=lock,
            arm_order_rows=snapshot.arm_order_rows,
            verify_source_files=False,
            verify_locked_artifacts=False,
            require_evaluator_correction=False,
        )
        self.assertEqual(issues, [])
        self.assertEqual(lock["frontend_completion_gate"]["completed"], 60)
        self.assertEqual(lock["d_resolution_gate"]["terminal"], 20)
        self.assertEqual(lock["backend_queue_lock_hash"], builder.lock_hash(lock))

    def test_code_artifact_probe_uses_required_governance_label(self) -> None:
        observed: list[tuple[Path, Path, str]] = []

        def path_state(root: Path, path: Path, *, label: str) -> str:
            observed.append((root, path, label))
            return "ABSENT"

        with mock.patch.object(
            builder.rooted_io, "path_state_rooted", side_effect=path_state
        ):
            builder.build_outputs(
                fixture_snapshot(applicable_windows=0),
                allocated_at="2026-08-08T00:00:00+08:00",
                method_hashes=HASHES[:5],
                include_code_records=True,
            )

        self.assertTrue(observed)
        self.assertTrue(
            all(
                root == builder.ROOT
                and label == "backend queue code artifact"
                for root, _path, label in observed
            )
        )

    def test_validator_requires_parent_precision_and_epoch_entrypoint_bundle(self) -> None:
        snapshot = fixture_snapshot(applicable_windows=0)
        outputs = builder.build_outputs(
            snapshot,
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
            include_code_records=False,
        )
        lock = json.loads(outputs[builder.BACKEND_QUEUE_LOCK])
        lock["mutable_registry_prefix"] = {
            "path": builder.display_path(builder.RUN_REGISTRY)
        }
        lock["evaluator_precision_correction"] = {
            "lock": {
                "path": builder.display_path(builder.EVALUATOR_CORRECTION_LOCK),
                "sha256": HASHES[5],
                "size_bytes": 1,
            },
            "correction_lock_hash": HASHES[6],
        }
        lock["evaluator_epoch_ns_correction"] = {
            "lock": {
                "path": builder.display_path(
                    builder.EVALUATOR_EPOCH_CORRECTION_LOCK
                ),
                "sha256": HASHES[6],
                "size_bytes": 1,
            },
            "epoch_ns_correction_lock_hash": HASHES[7],
            "entrypoint": "scripts/evaluate_vins_common_support_epoch_v2.py",
            "implementation_bundle_sha256": HASHES[3],
        }
        lock["backend_queue_lock_hash"] = builder.lock_hash(lock)
        issues = validator.validate_artifacts(
            queue_content=outputs[builder.BACKEND_QUEUE],
            allocation_content=outputs[builder.BACKEND_ALLOCATION],
            lock_payload=lock,
            arm_order_rows=snapshot.arm_order_rows,
            verify_source_files=False,
            verify_locked_artifacts=False,
            require_evaluator_correction=True,
        )
        self.assertFalse(
            [
                issue
                for issue in issues
                if issue.startswith("evaluator_")
                or issue == "mutable_registry_prefix_missing"
            ]
        )

        del lock["evaluator_epoch_ns_correction"]
        lock["backend_queue_lock_hash"] = builder.lock_hash(lock)
        missing = validator.validate_artifacts(
            queue_content=outputs[builder.BACKEND_QUEUE],
            allocation_content=outputs[builder.BACKEND_ALLOCATION],
            lock_payload=lock,
            arm_order_rows=snapshot.arm_order_rows,
            verify_source_files=False,
            verify_locked_artifacts=False,
            require_evaluator_correction=True,
        )
        self.assertIn("evaluator_epoch_ns_correction_missing", missing)

    def test_validator_rejects_runner_and_source_drift(self) -> None:
        snapshot = fixture_snapshot()
        outputs = builder.build_outputs(
            snapshot,
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
            include_code_records=False,
        )
        lock = json.loads(outputs[builder.BACKEND_QUEUE_LOCK])
        _fields, queue = validator.parse_csv(outputs[builder.BACKEND_QUEUE])
        queue[0]["runner_method"] = "xfeat"
        first_feature = next(row for row in queue if row["arm"] != builder.B0)
        first_feature["feature_bag_sha256"] = "0" * 64
        mutated = builder.render_csv(builder.QUEUE_FIELDS, queue)
        issues = validator.validate_artifacts(
            queue_content=mutated,
            allocation_content=outputs[builder.BACKEND_ALLOCATION],
            lock_payload=lock,
            arm_order_rows=snapshot.arm_order_rows,
            verify_source_files=False,
            verify_locked_artifacts=False,
            require_evaluator_correction=False,
        )
        self.assertTrue(any(issue.startswith("runner_identity:") for issue in issues))
        self.assertTrue(any(issue.startswith("allocation_join_mismatch:") for issue in issues))
        self.assertIn("queue_content_hash_mismatch", issues)


if __name__ == "__main__":
    unittest.main()
