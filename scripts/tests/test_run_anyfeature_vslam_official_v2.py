#!/usr/bin/env python3
"""Synthetic-only regression tests for the AnyFeature official runner v2."""

from __future__ import annotations

import concurrent.futures
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_anyfeature_vslam_official_v1 as v1
from scripts import run_anyfeature_vslam_official_v2 as v2
from scripts.tests.test_run_anyfeature_vslam_official_v1 import SyntheticFixture


class AnyFeatureOfficialRunnerV2Tests(unittest.TestCase):
    def temporary(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary, Path(temporary.name).resolve()

    def ldd_fixture(
        self,
    ) -> tuple[v1.FrozenAssets, Path, Path, Path, Path]:
        _, root = self.temporary()
        repo = root / "repo"
        runtime = root / "runtime"
        binary = repo / "bin/mono"
        core = repo / "lib/libAnyFeature-VSLAM.so"
        dbow2 = repo / "Thirdparty/DBoW2/lib/libDBoW2.so"
        opencv_target = runtime / "env/lib/libopencv_core.so.4.9.0"
        opencv_soname = runtime / "env/lib/libopencv_core.so.409"
        for path, payload in (
            (binary, b"binary"),
            (core, b"core"),
            (dbow2, b"dbow2"),
            (opencv_target, b"opencv-4.9"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        opencv_soname.symlink_to(opencv_target.name)
        lock = runtime / "evidence/lock.txt"
        lock.parent.mkdir(parents=True)
        lock.write_text("lock\n")
        vocabulary = runtime / "vocabulary"
        vocabulary.mkdir()
        provisioning = root / "provisioning.json"
        provisioning.write_text("{}\n")
        preregistration = root / "preregistration.md"
        preregistration.write_text("frozen\n")
        assets = v1.FrozenAssets(
            repo=repo,
            runtime_root=runtime,
            binary=binary,
            core_library=core,
            dbow2_library=dbow2,
            env_lock=lock,
            vocabulary_folder=vocabulary,
            provisioning_result=provisioning,
            preregistration=preregistration,
            expected_binary_sha256=v1.sha256_file(binary),
            expected_core_library_sha256=v1.sha256_file(core),
            expected_dbow2_library_sha256=v1.sha256_file(dbow2),
            expected_env_lock_sha256=v1.sha256_file(lock),
            expected_configs={},
            expected_vocabs={},
            enforce_git=True,
        )
        return assets, core, dbow2, opencv_target, opencv_soname

    @staticmethod
    def completed_ldd(text: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["/usr/bin/ldd", "synthetic"], 0, stdout=text, stderr=None
        )

    def test_v1_is_hash_bound_and_all_profiles_and_argv_are_unchanged(self) -> None:
        self.assertEqual(
            v1.sha256_file(Path(v1.__file__).resolve()),
            v2.EXPECTED_BASE_RUNNER_SHA256,
        )
        self.assertIs(v2.PROFILES, v1.PROFILES)
        self.assertEqual(tuple(v2.PROFILES), tuple(v1.PROFILES))
        for name in v1.PROFILES:
            with self.subTest(profile=name):
                self.assertIs(v2.PROFILES[name], v1.PROFILES[name])
                self.assertEqual(
                    v2.official_argv(v2.PROFILES[name], v2.FORMAL_ASSETS),
                    v1.official_argv(v1.PROFILES[name], v1.FORMAL_ASSETS),
                )
        identity = v2.runner_identity()
        self.assertEqual(identity["path"], str(Path(v2.__file__).resolve()))
        self.assertEqual(identity["sha256"], v2.sha256_file(Path(v2.__file__)))
        self.assertEqual(
            identity["base_runner"]["sha256"],
            v2.EXPECTED_BASE_RUNNER_SHA256,
        )

    def test_real_soname_symlink_is_equivalent_when_ldd_prints_dot409(self) -> None:
        assets, core, dbow2, opencv_target, opencv_soname = self.ldd_fixture()
        self.assertTrue(opencv_soname.is_symlink())
        self.assertEqual(opencv_soname.resolve(), opencv_target.resolve())
        text = (
            f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
            f"libDBoW2.so => {dbow2.resolve()} (0x2)\n"
            f"libopencv_core.so.409 => {opencv_soname} (0x3)\n"
        )
        completed = self.completed_ldd(text)
        with mock.patch.object(v2.subprocess, "run", return_value=completed):
            self.assertEqual(v2.audit_ldd(assets, {}), text)
        # The retained v1 behavior reproduces the sealed false negative: it
        # searches for the resolved .4.9.0 string although ldd prints .409.
        with mock.patch.object(v1.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                v1.ContractError, "LDD_REQUIRED_RESOLUTION_MISSING"
            ):
                v1.audit_ldd(assets, {})

    def test_real_target_rendering_is_equivalent_too(self) -> None:
        assets, core, dbow2, opencv_target, _opencv_soname = self.ldd_fixture()
        text = (
            f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
            f"libDBoW2.so => {dbow2.resolve()} (0x2)\n"
            f"libopencv_core.so.409 => {opencv_target.resolve()} (0x3)\n"
        )
        with mock.patch.object(
            v2.subprocess, "run", return_value=self.completed_ldd(text)
        ):
            self.assertEqual(v2.audit_ldd(assets, {}), text)

    def test_opencv_mapping_outside_frozen_environment_remains_rejected(self) -> None:
        assets, core, dbow2, opencv_target, _opencv_soname = self.ldd_fixture()
        outside = assets.runtime_root.parent / "outside/libopencv_core.so.409"
        outside.parent.mkdir(parents=True)
        outside.symlink_to(opencv_target)
        text = (
            f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
            f"libDBoW2.so => {dbow2.resolve()} (0x2)\n"
            f"libopencv_core.so.409 => {outside} (0x3)\n"
        )
        with mock.patch.object(
            v2.subprocess, "run", return_value=self.completed_ldd(text)
        ):
            with self.assertRaisesRegex(
                v2.ContractError, "LDD_OPENCV_OUTSIDE_FROZEN_ENV"
            ):
                v2.audit_ldd(assets, {})

    def test_frozen_soname_symlink_may_not_escape_the_environment(self) -> None:
        assets, core, dbow2, _opencv_target, opencv_soname = self.ldd_fixture()
        outside_target = assets.runtime_root.parent / "outside/libopencv_core.so.4.9.0"
        outside_target.parent.mkdir(parents=True)
        outside_target.write_bytes(b"outside-opencv")
        opencv_soname.unlink()
        opencv_soname.symlink_to(outside_target)
        text = (
            f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
            f"libDBoW2.so => {dbow2.resolve()} (0x2)\n"
            f"libopencv_core.so.409 => {opencv_soname} (0x3)\n"
        )
        with mock.patch.object(
            v2.subprocess, "run", return_value=self.completed_ldd(text)
        ):
            with self.assertRaisesRegex(
                v2.ContractError,
                "LDD_EXPECTED_OPENCV_TARGET_OUTSIDE_FROZEN_ENV",
            ):
                v2.audit_ldd(assets, {})

    def test_not_found_and_wrong_soname_target_remain_rejected(self) -> None:
        assets, core, dbow2, _opencv_target, _opencv_soname = self.ldd_fixture()
        cases = (
            (
                f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
                "libopencv_core.so.409 => not found\n",
                "LDD_CONTAINS_NOT_FOUND",
            ),
            (
                f"libAnyFeature-VSLAM.so => {core.resolve()} (0x1)\n"
                f"libDBoW2.so => {dbow2.resolve()} (0x2)\n"
                f"libopencv_core.so.410 => {assets.runtime_root}/env/lib/"
                "libopencv_core.so.409 (0x3)\n",
                "LDD_REQUIRED_EQUIVALENT_RESOLUTION_MISSING",
            ),
        )
        for text, error in cases:
            with self.subTest(error=error), mock.patch.object(
                v2.subprocess, "run", return_value=self.completed_ldd(text)
            ):
                with self.assertRaisesRegex(v2.ContractError, error):
                    v2.audit_ldd(assets, {})

    def test_v2_preflight_preserves_v1_semantics_and_seals_v2_identity(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "full")
        input_manifest = {
            "schema": v1.INPUT_SCHEMA,
            "profile": fixture.profile.input_profile,
            "frame_count": fixture.profile.frame_count,
            "files": [],
            "consumed_file_count": 0,
            "consumed_payload_tree_sha256": v1.sha256_bytes(b""),
        }
        with mock.patch.object(v2, "audit_ldd", return_value="synthetic ldd\n"), mock.patch.object(
            v2, "build_input_manifest", return_value=input_manifest
        ):
            bundle = v2.preflight(fixture.profile, fixture.assets, formal=False)
        self.assertEqual(
            bundle.argv, v1.official_argv(fixture.profile, fixture.assets)
        )
        self.assertEqual(bundle.preflight_summary["schema"], v2.RUNNER_SCHEMA)
        self.assertEqual(
            bundle.preflight_summary["semantic_fields"]["Feat"], "orb32"
        )
        self.assertEqual(
            bundle.preflight_summary["runner"]["base_runner"]["sha256"],
            v2.EXPECTED_BASE_RUNNER_SHA256,
        )

    def test_no_clobber_contract_and_v2_run_manifest_identity_are_preserved(self) -> None:
        _, root = self.temporary()
        fixture = SyntheticFixture(root, "full")
        original_schema = v1.RUNNER_SCHEMA
        original_identity = v1.runner_identity
        rc, manifest = v2.execute_run(fixture.bundle())
        self.assertEqual(rc, v2.RC_SUCCESS)
        self.assertEqual(manifest["schema"], v2.RUNNER_SCHEMA)
        self.assertEqual(
            manifest["runner"]["path"], str(Path(v2.__file__).resolve())
        )
        self.assertEqual(
            manifest["runner"]["base_runner"]["sha256"],
            v2.EXPECTED_BASE_RUNNER_SHA256,
        )
        self.assertEqual(manifest["trajectory_syntax"]["pose_count"], 1)
        self.assertFalse(manifest["accuracy_support"]["evaluated_by_runner"])
        self.assertEqual(v1.RUNNER_SCHEMA, original_schema)
        self.assertIs(v1.runner_identity, original_identity)
        with self.assertRaisesRegex(v2.ContractError, "OUTPUT_ALREADY_EXISTS"):
            v2.validate_profile_paths(
                fixture.profile, fixture.sequence, fixture.output
            )

    def test_concurrent_reused_executors_never_mutate_v1_globals(self) -> None:
        original_schema = v1.RUNNER_SCHEMA
        original_identity = v1.runner_identity
        overlap = threading.Barrier(3, timeout=10.0)

        def blocking_executor(_bundle):
            overlap.wait()
            overlap.wait()
            return 0, {"schema": RUNNER_SCHEMA, "runner": runner_identity()}

        with mock.patch.object(v2, "_V1_EXECUTE_RUN", blocking_executor):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(v2.execute_run, mock.sentinel.bundle_a),
                    pool.submit(v2.execute_run, mock.sentinel.bundle_b),
                ]
                overlap.wait()
                self.assertEqual(v1.RUNNER_SCHEMA, original_schema)
                self.assertIs(v1.runner_identity, original_identity)
                overlap.wait()
                results = [future.result(timeout=10.0) for future in futures]
        for rc, manifest in results:
            self.assertEqual(rc, 0)
            self.assertEqual(manifest["schema"], v2.RUNNER_SCHEMA)
            self.assertEqual(
                manifest["runner"]["path"], str(Path(v2.__file__).resolve())
            )
        self.assertEqual(v1.RUNNER_SCHEMA, original_schema)
        self.assertIs(v1.runner_identity, original_identity)


if __name__ == "__main__":
    unittest.main()
