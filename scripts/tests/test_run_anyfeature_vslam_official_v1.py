#!/usr/bin/env python3
"""Synthetic tests only; no official binary, dataset, or SLAM run is used."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from scripts import run_anyfeature_vslam_official_v1 as runner


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: bytes, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if executable:
        path.chmod(path.stat().st_mode | 0o111)
    return path


def _fake_binary(behavior: str) -> bytes:
    emit_budgets = behavior != "missing-budgets"
    exit_code = 9 if behavior == "nonzero" else 0
    diagnostic = (
        "print('failed to read r2d2 keypoints bin')"
        if behavior == "reader-diagnostic"
        else ""
    )
    trajectory = ""
    if behavior == "smoke-nonfinite-trajectory":
        trajectory = "1700000000.000000 0 0 0 0 0 nan 1\n"
    elif behavior not in ("smoke", "empty-full", "nonzero"):
        # Deliberately only one keyframe: this is syntactically usable and must
        # not be turned into a runtime failure by an accuracy-support threshold.
        trajectory = "1700000000.000000 0 0 0 0 0 0 1\n"
    budgets = (
        "print('- Number of Features: 2000')\n"
        "print('- Number of Features: 4000')"
        if emit_budgets
        else ""
    )
    source = f"""#!/usr/bin/env python3
import pathlib
import sys

values = {{}}
for token in sys.argv[1:]:
    key, value = token.split(':', 1)
    values[key] = value
print('AnyFeature path = ' + values['anyfeat'])
print('Path to vocabulary folder = ' + values['Voc'])
print('Feature settings yaml file = ' + values['FeatSet'])
print('Activate Visualization = ' + values['Vis'])
print('Path to sequence = ' + values['sequence_path'])
print('Path to output = ' + values['exp_folder'])
print('Exp id = ' + values['exp_id'])
print('Feature = ' + values['Feat'])
print('Fix image size = ' + values['FixRes'])
print('Images in the sequence: ' + str(len(pathlib.Path(values['sequence_path']).joinpath('rgb.txt').read_text().splitlines())))
{budgets}
{diagnostic}
out = pathlib.Path(values['exp_folder'])
out.joinpath('00000_KeyFrameTrajectory.txt').write_text({trajectory!r})
out.joinpath('00000_statistics.txt').write_text('0 0 0 nan\\n')
out.joinpath('00000_statistics.yaml').write_text('graph:\\n  numObservationsPerPt: .nan\\n')
raise SystemExit({exit_code})
"""
    return source.encode("utf-8")


class SyntheticFixture:
    def __init__(self, root: Path, behavior: str, *, smoke: bool = False) -> None:
        self.root = root
        self.repo = root / "repo"
        self.runtime = root / "runtime"
        self.sequence = root / "sequence"
        self.output = root / "result"
        self.binary = _write(
            self.repo / "bin/mono", _fake_binary(behavior), executable=True
        )
        self.core = _write(self.repo / "lib/libAnyFeature-VSLAM.so", b"core")
        self.dbow2 = _write(
            self.repo / "Thirdparty/DBoW2/lib/libDBoW2.so", b"dbow2"
        )
        self.orb_config = _write(
            self.repo / "settings/orb32_settings.yaml", b"orb-settings\n"
        )
        self.r2d2_config = _write(
            self.repo / "settings/r2d2_128_settings.yaml", b"r2d2-settings\n"
        )
        for name in (
            "env/bin",
            "env/lib",
            "home",
            "mamba-root",
            "pkgs",
            "pip-cache",
            "hf-cache",
            "xdg-cache",
            "tmp",
        ):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)
        self.lock = _write(self.runtime / "evidence/explicit.txt", b"lock\n")
        self.vocab = root / "vocabulary"
        self.orb_vocab = _write(self.vocab / "ORBvoc.txt", b"orb-vocabulary")
        self.r2d2_vocab = _write(
            self.vocab / "R2d2_DBoW2_voc.txt", b"r2d2-vocabulary"
        )
        self.provisioning = _write(root / "provisioning.json", b"{}\n")
        self.preregistration = _write(root / "preregistration.md", b"frozen\n")
        self.sequence.mkdir()
        frame_count = 1 if smoke else 3
        first_stamp = 1_700_000_000_000_000_000
        stamps = [first_stamp + i * 50_000_000 for i in range(frame_count)]
        self.sequence.joinpath("rgb.txt").write_text(
            "".join(
                f"{stamp // 1_000_000_000}.{stamp % 1_000_000_000:09d} "
                f"rgb/{stamp}.png\n"
                for stamp in stamps
            )
        )
        self.profile = runner.RunProfile(
            "synthetic-smoke" if smoke else "synthetic-full",
            self.sequence,
            self.output,
            "r2d2_128" if smoke else "orb32",
            frame_count,
            "synthetic-input",
            smoke,
            smoke,
            not smoke,
            None if smoke else 1,
        )
        self.assets = runner.FrozenAssets(
            self.repo,
            self.runtime,
            self.binary,
            self.core,
            self.dbow2,
            self.lock,
            self.vocab,
            self.provisioning,
            self.preregistration,
            _sha(self.binary),
            _sha(self.core),
            _sha(self.dbow2),
            _sha(self.lock),
            {
                "orb32": ("settings/orb32_settings.yaml", _sha(self.orb_config)),
                "r2d2_128": (
                    "settings/r2d2_128_settings.yaml",
                    _sha(self.r2d2_config),
                ),
            },
            {
                "ORBvoc.txt": (self.orb_vocab.stat().st_size, _sha(self.orb_vocab)),
                "R2d2_DBoW2_voc.txt": (
                    self.r2d2_vocab.stat().st_size,
                    _sha(self.r2d2_vocab),
                ),
            },
            enforce_git=False,
        )

    def bundle(self) -> runner.PreflightBundle:
        input_manifest = {
            "schema": runner.INPUT_SCHEMA,
            "profile": self.profile.input_profile,
            "frame_count": self.profile.frame_count,
            "files": [],
            "consumed_file_count": 0,
            "consumed_payload_tree_sha256": hashlib.sha256(b"").hexdigest(),
        }
        with mock.patch.object(runner, "audit_ldd", return_value="synthetic ldd\n"), mock.patch.object(
            runner, "build_input_manifest", return_value=input_manifest
        ):
            return runner.preflight(self.profile, self.assets, formal=False)


class AnyFeatureOfficialRunnerTests(unittest.TestCase):
    def temporary(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary, Path(temporary.name)

    def test_formal_profiles_and_exact_argv_are_frozen(self) -> None:
        self.assertEqual(runner.PROFILES["r2d2-smoke"].frame_count, 1)
        self.assertEqual(runner.PROFILES["orb32-full"].frame_count, 901)
        self.assertEqual(runner.PROFILES["r2d2-full"].frame_count, 901)
        self.assertEqual(
            [runner.PROFILES[name].order_position for name in ("orb32-full", "r2d2-full")],
            [1, 2],
        )
        argv = runner.official_argv(runner.PROFILES["orb32-full"], runner.FORMAL_ASSETS)
        self.assertEqual(
            argv[1:],
            (
                f"anyfeat:{runner.REPO}/",
                f"Voc:{runner.VOCABULARY_FOLDER}",
                f"FeatSet:{runner.REPO / 'settings/orb32_settings.yaml'}",
                "Vis:0",
                f"sequence_path:{runner.FULL_SEQUENCE}",
                f"exp_folder:{runner.ORB_EXPERIMENT}",
                "exp_id:0",
                "Feat:orb32",
                "FixRes:0",
            ),
        )
        with self.assertRaisesRegex(runner.ContractError, "UNKNOWN_OR_NONFROZEN_SEQUENCE_PATH"):
            runner.validate_profile_paths(
                runner.PROFILES["orb32-full"], Path("/tmp/not-frozen"), runner.ORB_EXPERIMENT
            )

    def test_asset_drift_and_no_clobber_fail_before_process(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "full")
        fixture.binary.write_bytes(fixture.binary.read_bytes() + b"drift")
        with self.assertRaisesRegex(runner.ContractError, "OFFICIAL_MONO_BINARY_SHA256_MISMATCH"):
            fixture.bundle()

        _, root2 = self.temporary()
        fixture2 = SyntheticFixture(root2, "full")
        fixture2.output.mkdir()
        with self.assertRaisesRegex(runner.ContractError, "OUTPUT_ALREADY_EXISTS"):
            fixture2.bundle()

    def test_camera_input_profile_and_frame_count_are_fail_closed(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "full")
        sequence = fixture.sequence
        rgb_dir = sequence / "rgb"
        rgb_dir.mkdir()
        rows = runner._parse_rgb(sequence, fixture.profile.frame_count)
        calibration = sequence / "calibration.yaml"
        calibration.write_text("%YAML:1.0\nCamera.w: 968\nCamera.h: 608\n")
        exporter = Path(runner.__file__).resolve().with_name(
            "export_aqualoc_to_anyfeature_v1.py"
        )
        images = []
        tree = [
            ("rgb.txt", _sha(sequence / "rgb.txt")),
            ("calibration.yaml", _sha(calibration)),
        ]
        for index, (stamp, relative) in enumerate(rows):
            image = np.full((608, 968), index, np.uint8)
            path = sequence / relative
            self.assertTrue(cv2.imwrite(str(path), image))
            binding = {
                "source_index": index,
                "raw_header_ns": stamp,
                "record_ns": stamp,
                "relative_path": relative,
                "source_pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "png_sha256": _sha(path),
                "png_size_bytes": path.stat().st_size,
                "pixel_identity_verified": True,
            }
            images.append(binding)
            tree.append((relative, binding["png_sha256"]))
        manifest = {
            "adapter_version": "aqualoc-anyfeature-camera-v1",
            "adapter_identity": {
                "script": "scripts/export_aqualoc_to_anyfeature_v1.py",
                "resolved_script": str(exporter),
                "sha256": _sha(exporter),
            },
            "status": "EXPORTED",
            "profile": fixture.profile.input_profile,
            "source": {
                "sha256": "a" * 64,
                "calibration": {"sha256": "b" * 64},
            },
            "camera": {
                "count": fixture.profile.frame_count,
                "source_indices_inclusive": [0, fixture.profile.frame_count - 1],
                "selected_header_ns_inclusive": [rows[0][0], rows[-1][0]],
                "schema": {
                    "topic": "/camera/image_raw",
                    "message_type": "sensor_msgs/Image",
                    "width": 968,
                    "height": 608,
                    "encoding": "mono8",
                    "nominal_fps": 20.0,
                },
                "rgb_txt": {
                    "sha256": _sha(sequence / "rgb.txt"),
                    "row_count": fixture.profile.frame_count,
                },
                "images": images,
            },
            "calibration": {"output_sha256": _sha(calibration)},
            "payload_tree_sha256_excluding_manifest": runner.aggregate_hash(
                sorted(tree)
            ),
        }
        identity_record = {
            "schema": "aqualoc-anyfeature-sequence-identity-v1",
            "adapter_version": "aqualoc-anyfeature-camera-v1",
            "adapter_sha256": _sha(exporter),
            "profile": fixture.profile.input_profile,
            "source_bag_sha256": "a" * 64,
            "source_calibration_sha256": "b" * 64,
            "rgb_txt_sha256": _sha(sequence / "rgb.txt"),
            "output_calibration_sha256": _sha(calibration),
            "images": [
                {
                    "source_index": row["source_index"],
                    "raw_header_ns": row["raw_header_ns"],
                    "relative_path": row["relative_path"],
                    "source_pixel_sha256": row["source_pixel_sha256"],
                    "png_sha256": row["png_sha256"],
                    "png_size_bytes": row["png_size_bytes"],
                }
                for row in images
            ],
        }
        manifest["sequence_identity"] = {
            "schema": "aqualoc-anyfeature-sequence-identity-v1",
            "record": identity_record,
            "sha256": runner.sha256_bytes(
                runner.canonical_json(identity_record).encode()
            ),
        }
        conversion = sequence / "conversion_manifest.json"
        conversion.write_text(runner.canonical_json(manifest))
        result = runner._camera_sequence_manifest(
            fixture.profile, verify_frozen_source_files=False
        )
        self.assertEqual(result["frame_count"], 3)

        manifest["profile"] = "wrong-profile"
        conversion.write_text(runner.canonical_json(manifest))
        with self.assertRaisesRegex(
            runner.ContractError, "CONVERSION_MANIFEST_PROFILE_OR_IDENTITY_MISMATCH"
        ):
            runner._camera_sequence_manifest(
                fixture.profile, verify_frozen_source_files=False
            )
        with self.assertRaisesRegex(runner.ContractError, "PROFILE_FRAME_COUNT_MISMATCH"):
            runner._parse_rgb(sequence, 4)

    def test_full_sparse_trajectory_is_usable_but_accuracy_unassessed(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "full")
        rc, manifest = runner.execute_run(fixture.bundle())
        self.assertEqual(rc, runner.RC_SUCCESS)
        self.assertEqual(manifest["status"], "FULL_RUN_SYNTACTICALLY_USABLE")
        self.assertEqual(manifest["trajectory_syntax"]["pose_count"], 1)
        self.assertTrue(manifest["runtime_usability"]["usable"])
        self.assertTrue(
            manifest["runtime_usability"]["low_keyframe_count_is_not_a_process_failure"]
        )
        self.assertFalse(manifest["accuracy_support"]["evaluated_by_runner"])
        stored = json.loads((fixture.output / "run_manifest.json").read_text())
        self.assertEqual(stored, manifest)
        # canonical_json(..., allow_nan=False) reached disk and parses strictly;
        # the only textual "NaN" is the documented smoke-statistics policy.
        self.assertIsInstance(stored["process"]["elapsed_seconds"], float)
        with self.assertRaisesRegex(runner.ContractError, "OUTPUT_ALREADY_EXISTS"):
            fixture.bundle()

    def test_smoke_allows_nan_only_in_empty_statistics(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "smoke", smoke=True)
        rc, manifest = runner.execute_run(fixture.bundle())
        self.assertEqual(rc, runner.RC_SUCCESS)
        self.assertEqual(manifest["status"], "SMOKE_R2D2_INGESTION_CLOSURE_PASSED")
        self.assertFalse(manifest["trajectory_syntax"]["nonempty"])
        self.assertTrue(manifest["runtime_usability"]["usable"])
        self.assertIn("nan", (fixture.output / "00000_statistics.txt").read_text())

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        bad = SyntheticFixture(
            Path(temporary.name), "smoke-nonfinite-trajectory", smoke=True
        )
        bad_rc, bad_manifest = runner.execute_run(bad.bundle())
        self.assertEqual(bad_rc, runner.RC_RUNTIME_OR_USABILITY)
        self.assertFalse(
            bad_manifest["runtime_usability"]["smoke_trajectory_interface_passed"]
        )

    def test_runtime_reader_budget_rc_and_full_syntax_failures_are_retained(self) -> None:
        cases = (
            ("reader-diagnostic", "prohibited_diagnostics"),
            ("missing-budgets", "feature_budget"),
            ("nonzero", "raw_return_code"),
            ("empty-full", "trajectory_syntax"),
        )
        for behavior, key in cases:
            with self.subTest(behavior=behavior):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                fixture = SyntheticFixture(Path(temporary.name), behavior)
                rc, manifest = runner.execute_run(fixture.bundle())
                self.assertEqual(rc, runner.RC_RUNTIME_OR_USABILITY)
                self.assertEqual(manifest["status"], "FULL_RUN_UNUSABLE_RETAINED")
                self.assertFalse(manifest["runtime_usability"]["usable"])
                self.assertTrue((fixture.output / "run_manifest.json").is_file())
                if key == "prohibited_diagnostics":
                    self.assertTrue(manifest["stdout_contract"][key])
                elif key == "feature_budget":
                    self.assertFalse(manifest["stdout_contract"][key]["passed"])
                elif key == "raw_return_code":
                    self.assertEqual(manifest["process"][key], 9)
                else:
                    self.assertFalse(manifest[key]["syntax_usable"])

    def test_trajectory_parser_rejects_nonfinite_and_duplicate_but_not_sparse(self) -> None:
        _, root = self.temporary()
        path = root / "trajectory.txt"
        path.write_text("1 0 0 0 0 0 0 1\n")
        self.assertTrue(runner.audit_trajectory(path)["syntax_usable"])
        path.write_text("1 0 0 0 0 0 nan 1\n")
        self.assertEqual(runner.audit_trajectory(path)["reason"], "TRAJECTORY_NONFINITE:0")
        path.write_text("1 0 0 0 0 0 0 1\n1 0 0 0 0 0 0 1\n")
        self.assertEqual(
            runner.audit_trajectory(path)["reason"],
            "TRAJECTORY_TIMESTAMPS_NOT_STRICT:1",
        )


if __name__ == "__main__":
    unittest.main()
