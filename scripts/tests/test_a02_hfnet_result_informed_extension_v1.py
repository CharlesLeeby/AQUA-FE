from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import a02_hfnet_result_informed_extension_v1 as profile
from scripts import export_aqualoc_a02_shared_4500_6300_v1 as old_shared
from scripts import export_aqualoc_a02_shared_4500_7200_result_informed_v1 as shared
from scripts import materialize_aqualoc_a02_4500_7200_result_informed_v1 as materializer
from scripts import run_hfnet_slam_a02_4500_7200_result_informed_headless_v5 as runner


class ResultInformedExtensionTests(unittest.TestCase):
    def test_frozen_window_is_exact_and_additive(self) -> None:
        self.assertEqual(profile.ROLE, "POST-FAILURE_RESULT-INFORMED_EXPLORATORY_INITIALIZATION_CONTINUATION")
        self.assertEqual((profile.FEED_FIRST, profile.FEED_LAST, profile.FEED_COUNT), (4500, 7200, 2701))
        self.assertEqual((profile.SCORE_FIRST, profile.SCORE_LAST), (6300, 7200))
        self.assertEqual((len(profile.SCORE_REFERENCE_INDICES), profile.SCORE_EVALUATION_GRID_COUNT), (46, 45))
        self.assertEqual(profile.PRIOR_PREFIX_COUNT + profile.NEW_CAMERA_COUNT, profile.FEED_COUNT)
        self.assertEqual(profile.SCORE_REFERENCE_INDICES, tuple(range(6300, 7201, 20)))
        self.assertEqual(profile.SCORE_SPAN_NS, 44_989_672_064)
        self.assertNotEqual(profile.NEW_WINDOW_BAG, profile.OLD_WINDOW_BAG)
        self.assertNotEqual(profile.NEW_SHARED_ROOT, profile.OLD_SHARED_ROOT)
        self.assertNotIn("4500_6300", str(profile.NEW_RESULT))

    def test_materializer_command_has_no_runtime_choice_or_retry(self) -> None:
        command = materializer.converter_command(Path("/tmp/candidate.bag"), python="/usr/bin/python3.8")
        self.assertEqual(command.count("--start-index"), 1)
        self.assertEqual(command[command.index("--start-index") + 1], "4500")
        self.assertEqual(command[command.index("--end-index") + 1], "7200")
        self.assertEqual(command[command.index("--imu-margin-s") + 1], "0.25")
        self.assertNotIn("8100", command)
        self.assertNotIn("--resume", command)
        self.assertNotIn("--retry", command)
        self.assertEqual(materializer.EXPECTED_TOPIC_COUNTS, {"/camera/image_raw": 2701, "/rtimulib_node/imu": 27076, "/aqualoc/colmap_gt": 136})

    def test_materializer_preflight_does_not_create_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "absent" / "window.bag"
            manifest = root / "absent" / "window.bag.manifest.json"
            fake = {
                "raw_tar": {},
                "ground_truth": {},
                "converter": {},
                "prior_hfnet_unusable_result": {},
            }
            with mock.patch.object(profile, "NEW_WINDOW_BAG", output), mock.patch.object(profile, "NEW_WINDOW_MANIFEST", manifest), mock.patch.object(materializer, "_source_identities", return_value=fake), mock.patch("sys.stdout", new=io.StringIO()):
                rc = materializer.main(["--action", "preflight"])
            self.assertEqual(rc, 0)
            self.assertFalse(output.parent.exists())

    def test_all_entrypoints_reject_path_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(materializer.main(["--action", "preflight", "--output-bag", str(root / "other.bag")]), 2)
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(shared.main(["--action", "audit", "--output", str(root / "other")]), 2)
            altered = runner.replace(runner.DEFAULT_SPEC, result=root / "other-result")
            decision = runner.preflight(altered)
            self.assertFalse(decision["ready"])
            self.assertIn("FROZEN_SPEC_PATH_OVERRIDE_FORBIDDEN", decision["errors"])

    def test_materializer_failed_converter_claims_permanent_no_retry_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "window.bag"
            manifest = root / "window.bag.manifest.json"
            attempt = root / "window.bag.attempt.json"
            fake_sources = {
                "raw_tar": {"path": "/raw", "size_bytes": 1, "sha256": "1" * 64},
                "ground_truth": {"path": "/gt", "size_bytes": 1, "sha256": "2" * 64},
                "converter": {"path": "/converter", "size_bytes": 1, "sha256": "3" * 64},
                "prior_hfnet_unusable_result": {"path": "/result", "size_bytes": 1, "sha256": "4" * 64},
            }
            failed = subprocess.CompletedProcess(["converter"], 7)
            with mock.patch.object(profile, "NEW_WINDOW_BAG", output), mock.patch.object(profile, "NEW_WINDOW_MANIFEST", manifest), mock.patch.object(profile, "NEW_WINDOW_ATTEMPT", attempt), mock.patch.object(materializer, "_source_identities", return_value=fake_sources), mock.patch.object(materializer.subprocess, "run", return_value=failed) as execute, mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(materializer.main(["--action", "export"]), 2)
                self.assertTrue(attempt.is_file())
                self.assertFalse(output.exists())
                self.assertFalse(manifest.exists())
                self.assertEqual(materializer.main(["--action", "export"]), 2)
                self.assertEqual(execute.call_count, 1)

    def test_shared_prepare_failure_claims_permanent_no_retry_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "shared.attempt.json"
            record = {"schema_version": "synthetic", "no_retry": True}
            with mock.patch.object(profile, "NEW_SHARED_ATTEMPT", attempt), mock.patch.object(shared, "build_export_attempt_record", return_value=record), mock.patch.object(shared, "prepare", side_effect=shared.ContractError("synthetic prepare failure")), mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(shared.main(["--action", "export"]), 2)
                self.assertTrue(attempt.is_file())
                self.assertEqual(shared.main(["--action", "export"]), 2)

    def test_pair_publication_rolls_back_first_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial_bag, partial_manifest = root / "partial.bag", root / "partial.json"
            output_bag, output_manifest = root / "out.bag", root / "out.json"
            partial_bag.write_bytes(b"bag")
            partial_manifest.write_bytes(b"manifest")
            calls = 0

            def failing_second_link(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic second publication failure")
                os.link(source, target)

            with self.assertRaises(OSError):
                materializer.publish_pair_no_clobber(partial_bag, partial_manifest, output_bag, output_manifest, link=failing_second_link)
            self.assertFalse(output_bag.exists())
            self.assertFalse(output_manifest.exists())
            self.assertTrue(partial_bag.exists())
            self.assertTrue(partial_manifest.exists())

    def _small_prefix(self, root: Path, *, count: int = 3) -> tuple[list[old_shared.CameraSample], str]:
        rows = []
        cameras = []
        for relative in range(count):
            stamp = 1_000_000_000 + relative * 50_000_000
            pixels = bytes([relative + 1]) * 4
            source_hash = hashlib.sha256(pixels).hexdigest()
            png = b"synthetic-png-" + bytes([relative])
            target = root / f"shared/cam0/data/{stamp}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
            rows.append({"relative_index": relative, "global_source_index": 4500 + relative, "raw_header_ns": stamp, "source_pixel_sha256": source_hash, "png_sha256": hashlib.sha256(png).hexdigest(), "png_size_bytes": len(png), "materialization": "encoded_new_lossless", "relative_path": f"shared/cam0/data/{stamp}.png"})
            cameras.append(old_shared.CameraSample(relative, 4500 + relative, stamp, stamp, 2, 2, "mono8", 2, pixels, source_hash))
        manifest = {"schema_version": old_shared.SCHEMA_VERSION, "status": old_shared.STATUS_EXPORTED, "camera": {"images": rows}}
        payload = old_shared.canonical_json_bytes(manifest)
        (root / "conversion_manifest.json").write_bytes(payload)
        return cameras, hashlib.sha256(payload).hexdigest()

    def test_prefix_reuse_checks_every_source_and_png_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cameras, manifest_hash = self._small_prefix(root)
            identity, rows = shared.validate_prefix_rows(root, cameras, manifest_sha256=manifest_hash, expected_count=3)
            self.assertTrue(identity["per_frame_source_pixel_and_png_identity_rehashed"])
            self.assertEqual(len(rows), 3)
            (root / f"shared/cam0/data/{cameras[1].header_ns}.png").write_bytes(b"tampered")
            with self.assertRaisesRegex(shared.ContractError, "PREFIX_PNG_IDENTITY_MISMATCH:1"):
                shared.validate_prefix_rows(root, cameras, manifest_sha256=manifest_hash, expected_count=3)

    def test_prefix_and_trajectory_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "prefix"
            root.mkdir()
            cameras, manifest_hash = self._small_prefix(root)
            data = root / "shared/cam0/data"
            outside = Path(directory) / "outside-data"
            data.rename(outside)
            data.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(shared.ContractError, "SYMLINK_COMPONENT_FORBIDDEN"):
                shared.validate_prefix_rows(root, cameras, manifest_sha256=manifest_hash, expected_count=3)

            result = Path(directory) / "result"
            result.mkdir()
            external = Path(directory) / "external-trajectory.txt"
            external.write_text(self._trajectory_row(1_000_000_000_000), encoding="ascii")
            (result / "trajectory.txt").symlink_to(external)
            camera = [1_000_000_000_000 + index * 50_000_000 for index in range(profile.FEED_COUNT)]
            decision = runner._parse_trajectory(result / "trajectory.txt", camera, keyframes=False)
            self.assertFalse(decision["gate_pass"])
            self.assertIn("SYMLINK_FORBIDDEN", decision["errors"][0])

    def test_png_audit_binds_pixels_to_locked_bag_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            pixels = bytes((1, 2, 3, 4))
            sample = old_shared.CameraSample(0, 4500, 1_000_000_000, 1_000_000_000, 2, 2, "mono8", 2, pixels, hashlib.sha256(pixels).hexdigest())
            path.write_bytes(old_shared.encode_lossless_png(sample))
            shared._validate_png_pixels(path, sample, "SYNTHETIC")
            changed = bytes((1, 2, 3, 5))
            changed_sample = old_shared.CameraSample(0, 4500, 1_000_000_000, 1_000_000_000, 2, 2, "mono8", 2, changed, hashlib.sha256(changed).hexdigest())
            path.write_bytes(old_shared.encode_lossless_png(changed_sample))
            with self.assertRaisesRegex(shared.ContractError, "PIXELS_DIFFER_FROM_LOCKED_BAG"):
                shared._validate_png_pixels(path, sample, "SYNTHETIC")

    def test_shared_export_reservation_is_no_clobber_and_failure_consumes_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reserved-output"
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with shared.reserved_output_directory(output) as reserved:
                    (reserved / "partial.marker").write_text("partial", encoding="ascii")
                    raise RuntimeError("synthetic failure")
            self.assertEqual((output / "partial.marker").read_text(encoding="ascii"), "partial")
            with self.assertRaisesRegex(shared.ContractError, "OUTPUT_ALREADY_EXISTS"):
                with shared.reserved_output_directory(output):
                    pass

    @staticmethod
    def _trajectory_row(stamp: int) -> str:
        return f"{stamp}.000000 0 0 0 0 0 0 1\n"

    def test_trajectory_gate_uses_only_frozen_score_window(self) -> None:
        camera = [1_000_000_000_000 + index * 50_000_000 for index in range(profile.FEED_COUNT)]
        passing_indices = [1800 + index * 8 for index in range(30)]
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "trajectory.txt"
            trajectory.write_text("".join(self._trajectory_row(camera[index]) for index in passing_indices), encoding="ascii")
            decision = runner._parse_trajectory(trajectory, camera, keyframes=False)
            self.assertTrue(decision["gate_pass"])
            self.assertEqual(decision["score_pose_count"], 30)
            self.assertGreaterEqual(decision["score_span_seconds"], 10.0)

            trajectory.write_text("".join(self._trajectory_row(camera[index]) for index in range(1800, 1830)), encoding="ascii")
            short = runner._parse_trajectory(trajectory, camera, keyframes=False)
            self.assertFalse(short["gate_pass"])
            self.assertEqual(short["score_pose_count"], 30)
            self.assertLess(short["score_span_seconds"], 10.0)

            trajectory.write_text("".join(self._trajectory_row(camera[index]) for index in (1799, 1800, 1840)), encoding="ascii")
            keyframes = runner._parse_trajectory(trajectory, camera, keyframes=True)
            self.assertTrue(keyframes["gate_pass"])
            self.assertEqual(keyframes["score_pose_count"], 2)

    def test_runner_exposes_no_resume_retry_or_window_override(self) -> None:
        destinations = {action.dest for action in runner.parser()._actions}
        self.assertFalse({"start_index", "end_index", "score_start", "score_end", "atlas", "resume", "retry"} & destinations)
        contract = runner.build_contract({"synthetic": True}, runner.DEFAULT_SPEC)
        policy = contract["execution_policy"]
        self.assertEqual(policy["maximum_process_starts"], 1)
        self.assertIs(policy["retry"], False)
        self.assertIs(policy["atlas_resume"], False)
        self.assertIs(policy["extend_to_8100"], False)
        self.assertEqual(policy["start_from_scratch_at_global_camera"], 4500)

    def test_run_roots_are_reserved_and_local_immutable_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = runner.replace(runner.DEFAULT_SPEC, result=root / "result", evidence=root / "evidence")
            runner.reserve_run_roots(spec)
            self.assertTrue(spec.result.is_dir())
            self.assertTrue(spec.evidence.is_dir())
            with self.assertRaisesRegex(runner.ContractError, "RESULT_ROOT_ALREADY_EXISTS"):
                runner.reserve_run_roots(spec)

            model = root / "model"
            model.mkdir()
            onnx = model / "HF-Net.onnx"
            config = root / "runtime.yaml"
            onnx.write_bytes(b"onnx")
            config.write_bytes(b"config")
            staged = {"model_dir": str(model), "onnx": runner.identity(onnx), "derived_config": runner.identity(config)}
            audited = runner.audit_run_local_immutables(staged)
            self.assertTrue(audited["onnx_unchanged"])
            config.write_bytes(b"tampered")
            with self.assertRaisesRegex(runner.ContractError, "RUN_LOCAL_ONNX_OR_DERIVED_CONFIG_CHANGED"):
                runner.audit_run_local_immutables(staged)

    def test_authoritative_commands_and_invocation_environment_are_fail_closed(self) -> None:
        commands = profile.authoritative_commands()
        self.assertEqual([row["ordinal"] for row in commands], list(range(9)))
        self.assertEqual(commands[-1]["action"], "hfnet_one_shot_run")
        self.assertEqual(sum(bool(row["may_start_slam"]) for row in commands), 1)
        flattened = "\n".join(" ".join(row["argv"]) for row in commands)
        self.assertNotIn("8100", flattened)
        self.assertNotIn("--retry", flattened)
        self.assertNotIn("--resume", flattened)
        self.assertNotIn("--atlas", flattened)
        profile.audit_sealed_invocation_environment()
        with mock.patch.dict(os.environ, {**profile.REQUIRED_ENVIRONMENT, "ROGUE": "1"}, clear=True):
            with self.assertRaisesRegex(profile.ExtensionError, "INVOCATION_ENVIRONMENT_NOT_EXACTLY_SEALED"):
                profile.audit_sealed_invocation_environment()

    def test_static_freeze_is_executable_contract_and_outputs_are_still_absent(self) -> None:
        audited = runner.audit_static_freeze(runner.DEFAULT_SPEC)
        self.assertEqual(audited["value"]["authoritative_commands"], profile.authoritative_commands())
        self.assertTrue(audited["value"]["execution_environment"]["clear_parent_environment"])
        self.assertTrue(all(not path.exists() and not path.is_symlink() for path in profile.reserved_paths()))

    def test_static_freeze_rejects_extra_authority(self) -> None:
        value = json.loads(profile.STATIC_FREEZE.read_text(encoding="utf-8"))
        value["unauthorized"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered-freeze.json"
            path.write_bytes(profile.canonical_json_bytes(value))
            spec = runner.replace(runner.DEFAULT_SPEC, static_freeze=path)
            with mock.patch.object(profile, "STATIC_FREEZE", path), self.assertRaisesRegex(runner.ContractError, "TOP_LEVEL_KEYSET_MISMATCH"):
                runner.audit_static_freeze(spec)

    def test_static_freeze_has_honest_result_informed_controls(self) -> None:
        value = json.loads(profile.STATIC_FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(value["scientific_role"], profile.ROLE)
        design = value["design"]
        self.assertEqual(design["score_global_camera_indices_inclusive"], [6300, 7200])
        self.assertEqual(design["score_reference_pose_count"], 46)
        self.assertEqual(design["score_evaluation_grid_count"], 45)
        self.assertIs(design["atlas_resume"], False)
        self.assertIs(design["retry"], False)
        self.assertIs(design["failure_triggered_extension_to_8100"], False)
        self.assertEqual(value["prior_observation"]["interpretation"], "used_only_to motivate a separately frozen exploratory continuation; not confirmatory and not a retry")


if __name__ == "__main__":
    unittest.main()
