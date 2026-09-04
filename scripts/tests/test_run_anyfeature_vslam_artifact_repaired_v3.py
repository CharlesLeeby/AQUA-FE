#!/usr/bin/env python3
"""Synthetic and read-only contract tests for artifact-repaired runner v3."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import run_anyfeature_vslam_artifact_repaired_v3 as v3
from scripts import run_anyfeature_vslam_official_v1 as v1
from scripts import run_anyfeature_vslam_official_v2 as v2
from scripts.tests.test_run_anyfeature_vslam_official_v1 import SyntheticFixture


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_stdout(profile: v1.RunProfile, assets: v1.FrozenAssets) -> str:
    output = profile.experiment_folder.resolve()
    lines = (
        f"AnyFeature path = {str(assets.repo.resolve()).rstrip('/')}/",
        f"Path to vocabulary folder = {assets.vocabulary_folder.resolve()}",
        f"Feature settings yaml file = {v3.REPAIRED_R2D2_SETTINGS.resolve()}",
        "Activate Visualization = 0",
        f"Path to sequence = {profile.sequence_path.resolve()}",
        f"Path to output = {output}",
        "Exp id = 0",
        "Feature = r2d2_128",
        "Fix image size = 0",
        f"Loading Feature Matcher Settings from : {v3.REPAIRED_R2D2_SETTINGS.resolve()}",
        "- matchingTh: 0.38",
        f"Loading Feature Extractor Settings from : {v3.REPAIRED_R2D2_SETTINGS.resolve()}",
        "- numOctaves: 1",
        "- scaleFactor: 2",
        "- detectionTh: 1",
        "- Number of Features: 2000",
        "- Number of Features: 4000",
        "Start processing sequence ...",
        "Images in the sequence: 1",
        "median tracking time: 0.01",
        "mean tracking time: 0.01",
        f"Saving keyframe trajectory to {output}/00000_KeyFrameTrajectory.txt ...",
        "trajectory saved!",
        f"{output}/00000_statistics.yaml file written successfully!",
    )
    return "\n".join(lines) + "\n"


class AnyFeatureArtifactRepairedRunnerV3Tests(unittest.TestCase):
    def temporary(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary, Path(temporary.name).resolve()

    def test_base_runners_are_hash_bound_and_only_new_smoke_is_exposed(self) -> None:
        self.assertEqual(
            v1.sha256_file(Path(v1.__file__).resolve()),
            v3.EXPECTED_BASE_V1_SHA256,
        )
        self.assertEqual(
            v1.sha256_file(Path(v2.__file__).resolve()),
            v3.EXPECTED_BASE_V2_SHA256,
        )
        self.assertEqual(tuple(v3.PROFILES), (v3.PROFILE.name,))
        self.assertTrue(v3.PROFILE.smoke_only)
        self.assertFalse(v3.PROFILE.evaluation_eligible)
        self.assertEqual(v3.PROFILE.frame_count, 1)
        self.assertNotEqual(
            v3.PROFILE.experiment_folder, v1.PROFILES["r2d2-smoke"].experiment_folder
        )

    def test_repair_is_exactly_one_deleted_suffix_byte(self) -> None:
        repair = v3.verify_artifact_repair()
        delta = repair["exact_transformation"]
        self.assertEqual(delta["line"], 11)
        self.assertEqual(delta["byte_delta"], -1)
        self.assertEqual(delta["other_bytes_changed"], 0)
        self.assertFalse(delta["numeric_value_changed"])
        self.assertFalse(delta["algorithm_parameter_changed"])
        self.assertFalse(repair["official_tree_modified"])

        _, root = self.temporary()
        official = root / "official.yaml"
        repaired = root / "repaired.yaml"
        official.write_bytes(v3.OFFICIAL_R2D2_SETTINGS.read_bytes())
        repaired.write_bytes(v3.REPAIRED_R2D2_SETTINGS.read_bytes() + b"# drift\n")
        with self.assertRaisesRegex(
            v3.ContractError, "REPAIRED_SETTINGS_HAS_UNAUTHORIZED_DELTA"
        ):
            v3.verify_artifact_repair(
                official,
                repaired,
                expected_official_hash=_sha(official),
                expected_repaired_hash=_sha(repaired),
            )

    def test_frozen_opencv_49_reads_exact_types_and_values(self) -> None:
        environment = v1.child_environment(v3.FORMAL_ASSETS)
        probe = v3.opencv_settings_probe(environment)
        self.assertEqual(probe["status"], "PASS")
        self.assertEqual(probe["opencv_version"], "4.9.0")
        self.assertEqual(
            probe["values"]["FeatureMatcher.matchingTh"], 0.38
        )
        self.assertEqual(
            probe["node_types"]["FeatureMatcher.matchingTh"], "real"
        )

    def test_argv_uses_project_copy_and_never_changes_official_tree(self) -> None:
        argv = v3.official_argv(v3.PROFILE, v3.FORMAL_ASSETS)
        self.assertIn(f"FeatSet:{v3.REPAIRED_R2D2_SETTINGS.resolve()}", argv)
        self.assertNotIn(f"FeatSet:{v3.OFFICIAL_R2D2_SETTINGS.resolve()}", argv)
        self.assertIn(f"exp_folder:{v3.REPAIRED_SMOKE_EXPERIMENT}", argv)
        self.assertEqual(
            v1.sha256_file(v3.OFFICIAL_R2D2_SETTINGS),
            v3.EXPECTED_OFFICIAL_SETTINGS_SHA256,
        )

    def test_exact_post_loop_teardown_is_narrowly_accepted(self) -> None:
        stdout = valid_stdout(v3.PROFILE, v3.FORMAL_ASSETS)
        contract = v3._stdout_contract(
            v3.PROFILE,
            v3.FORMAL_ASSETS,
            stdout,
            v3.KNOWN_TEARDOWN_STDERR + "\n",
        )
        self.assertTrue(contract["pre_exit_ingestion_contract_passed"])
        self.assertFalse(contract["hard_blockers"])
        classification = v3.classify_known_post_loop_teardown(
            134,
            v3.KNOWN_TEARDOWN_STDERR + "\n",
            contract,
            True,
        )
        self.assertTrue(classification["recognized"])
        self.assertTrue(classification["accepted_for_ingestion_smoke_only"])
        self.assertTrue(classification["does_not_make_process_exit_clean"])

        for rc, stderr, artifacts in (
            (139, v3.KNOWN_TEARDOWN_STDERR + "\n", True),
            (134, "terminate called after throwing an exception\n", True),
            (134, v3.KNOWN_TEARDOWN_STDERR + "\n", False),
        ):
            with self.subTest(rc=rc, stderr=stderr, artifacts=artifacts):
                candidate_contract = v3._stdout_contract(
                    v3.PROFILE, v3.FORMAL_ASSETS, stdout, stderr
                )
                result = v3.classify_known_post_loop_teardown(
                    rc, stderr, candidate_contract, artifacts
                )
                self.assertFalse(result["accepted_for_ingestion_smoke_only"])

    def test_reader_and_initialization_errors_always_override_teardown(self) -> None:
        base = valid_stdout(v3.PROFILE, v3.FORMAL_ASSETS)
        cases = (
            "failed to read r2d2 descriptors .bin\n",
            "OpenCV(4.9.0) error: assertion failed\n",
            "Wrong initialization, reseting...\n",
            "Not enough motion for initializing. Reseting...\n",
        )
        for diagnostic in cases:
            with self.subTest(diagnostic=diagnostic.strip()):
                contract = v3._stdout_contract(
                    v3.PROFILE,
                    v3.FORMAL_ASSETS,
                    base + diagnostic,
                    v3.KNOWN_TEARDOWN_STDERR + "\n",
                )
                self.assertTrue(contract["hard_blockers"])
                self.assertFalse(contract["pre_exit_ingestion_contract_passed"])
                classification = v3.classify_known_post_loop_teardown(
                    134,
                    v3.KNOWN_TEARDOWN_STDERR + "\n",
                    contract,
                    True,
                )
                self.assertFalse(
                    classification["accepted_for_ingestion_smoke_only"]
                )

    def test_missing_loop_completion_cannot_be_called_post_loop(self) -> None:
        stdout = valid_stdout(v3.PROFILE, v3.FORMAL_ASSETS).replace(
            f"{v3.PROFILE.experiment_folder.resolve()}/00000_statistics.yaml "
            "file written successfully!\n",
            "",
        )
        contract = v3._stdout_contract(
            v3.PROFILE,
            v3.FORMAL_ASSETS,
            stdout,
            v3.KNOWN_TEARDOWN_STDERR + "\n",
        )
        self.assertFalse(contract["pre_exit_ingestion_contract_passed"])
        classification = v3.classify_known_post_loop_teardown(
            134,
            v3.KNOWN_TEARDOWN_STDERR + "\n",
            contract,
            True,
        )
        self.assertFalse(classification["accepted_for_ingestion_smoke_only"])

    def test_synthetic_executor_seals_nonclean_but_usable_teardown(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "smoke", smoke=True)
        profile = replace(
            fixture.profile,
            name="synthetic-repaired-smoke",
            feature="r2d2_128",
            smoke_only=True,
            evaluation_eligible=False,
        )
        script = f"""#!/usr/bin/env python3
import pathlib
import sys

values = {{}}
for token in sys.argv[1:]:
    key, value = token.split(':', 1)
    values[key] = value
out = pathlib.Path(values['exp_folder'])
print('AnyFeature path = ' + values['anyfeat'])
print('Path to vocabulary folder = ' + values['Voc'])
print('Feature settings yaml file = ' + values['FeatSet'])
print('Activate Visualization = ' + values['Vis'])
print('Path to sequence = ' + values['sequence_path'])
print('Path to output = ' + values['exp_folder'])
print('Exp id = ' + values['exp_id'])
print('Feature = ' + values['Feat'])
print('Fix image size = ' + values['FixRes'])
print('Loading Feature Matcher Settings from : ' + values['FeatSet'])
print('- matchingTh: 0.38')
print('Loading Feature Extractor Settings from : ' + values['FeatSet'])
print('- numOctaves: 1')
print('- scaleFactor: 2')
print('- detectionTh: 1')
print('- Number of Features: 2000')
print('- Number of Features: 4000')
print('Start processing sequence ...')
print('Images in the sequence: 1')
print('median tracking time: 0.01')
print('mean tracking time: 0.01')
print('Saving keyframe trajectory to ' + str(out / '00000_KeyFrameTrajectory.txt') + ' ...')
out.joinpath('00000_KeyFrameTrajectory.txt').write_text('')
print('trajectory saved!')
out.joinpath('00000_statistics.txt').write_text('0 0 0 nan\\n')
out.joinpath('00000_statistics.yaml').write_text('graph:\\n  numObservationsPerPt: .nan\\n')
print(str(out / '00000_statistics.yaml') + ' file written successfully!')
print({v3.KNOWN_TEARDOWN_STDERR!r}, file=sys.stderr)
raise SystemExit(134)
"""
        fixture.binary.write_text(script)
        fixture.binary.chmod(fixture.binary.stat().st_mode | 0o111)
        assets = replace(
            fixture.assets,
            expected_binary_sha256=_sha(fixture.binary),
        )
        environment = v1.child_environment(assets)
        input_manifest = {
            "schema": v1.INPUT_SCHEMA,
            "profile": profile.input_profile,
            "frame_count": 1,
            "files": [],
            "consumed_file_count": 0,
            "consumed_payload_tree_sha256": hashlib.sha256(b"").hexdigest(),
        }
        repair = v3.verify_artifact_repair()
        official = {
            "binary": v1.file_binding(fixture.binary, "BINARY"),
            "environment_explicit_lock": v1.file_binding(fixture.lock, "LOCK"),
            "project_side_artifact_repair": repair,
        }
        semantic = {
            "anyfeat": str(assets.repo.resolve()).rstrip("/") + "/",
            "Voc": str(assets.vocabulary_folder.resolve()),
            "FeatSet": str(v3.REPAIRED_R2D2_SETTINGS.resolve()),
            "Vis": 0,
            "sequence_path": str(profile.sequence_path.resolve()),
            "exp_folder": str(profile.experiment_folder.resolve()),
            "exp_id": 0,
            "Feat": "r2d2_128",
            "FixRes": 0,
        }
        summary = {
            "semantic_fields": semantic,
            "artifact_repair": repair,
            "opencv_settings_probe": {"status": "synthetic-test-only"},
        }
        bundle = v1.PreflightBundle(
            profile,
            assets,
            official,
            input_manifest,
            v3.official_argv(profile, assets),
            environment,
            "synthetic ldd closed\n",
            summary,
        )
        rc, manifest = v3.execute_run(bundle)
        self.assertEqual(rc, v3.RC_SUCCESS)
        self.assertFalse(manifest["process"]["clean_exit"])
        self.assertTrue(
            manifest["post_loop_teardown_classification"][
                "accepted_for_ingestion_smoke_only"
            ]
        )
        self.assertTrue(manifest["runtime_usability"]["ingestion_closure_usable"])
        self.assertFalse(manifest["runtime_usability"]["process_fully_successful"])
        sealed = json.loads(
            (profile.experiment_folder / "run_manifest.json").read_text()
        )
        self.assertEqual(sealed["status"], manifest["status"])


if __name__ == "__main__":
    unittest.main()
