from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_orbslam3_seeded_triplet.sh"


def parse_manifest(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


class OrbSlam3SeededTripletRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.orb_root = self.root / "orb"
        binary = self.orb_root / "Examples_old" / "Monocular" / "mono_euroc_old"
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "printf 'seed=%s\\n' \"${ORB_SLAM3_EXTERNAL_SEEDS-<unset>}\"\n"
            "printf 'audit=%s\\n' \"${ORB_SLAM3_SEED_AUDIT_DIR-<unset>}\"\n"
            "printf 'audit_enable=%s\\n' \"${ORB_SLAM3_ENABLE_SEED_AUDIT-<unset>}\"\n"
            "printf 'compat_audit_dir=%s\\n' \"${ORB_SLAM3_EXTERNAL_SEED_AUDIT_DIR-<unset>}\"\n"
            "printf 'compat_audit_enable=%s\\n' \"${ORB_SLAM3_EXTERNAL_SEED_AUDIT-<unset>}\"\n"
            "printf 'compat_audit_capacity=%s\\n' \"${ORB_SLAM3_EXTERNAL_SEED_AUDIT_MAX_EVENTS-<unset>}\"\n"
            "printf 'lineage_bridge=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE-<unset>}\"\n"
            "printf 'lineage_min_quality=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY-<unset>}\"\n"
            "printf 'lineage_max_projection_error=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX-<unset>}\"\n"
            "printf 'lineage_max_descriptor_distance=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE-<unset>}\"\n"
            "printf 'lineage_cull_grace_keyframes=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES-<unset>}\"\n"
            "printf 'lineage_max_assisted_matches=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES-<unset>}\"\n"
            "printf 'lineage_native_birth_only=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY-<unset>}\"\n"
            "printf 'lineage_quarantine_on_outlier=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER-<unset>}\"\n"
            "printf 'lineage_terminal_quarantine=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE-<unset>}\"\n"
            "printf 'lineage_quarantine_enforce=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE-<unset>}\"\n"
            "printf 'lineage_pre_kf_outlier_purge=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE-<unset>}\"\n"
            "printf 'lineage_pre_kf_outlier_purge_enforce=%s\\n' \"${ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE-<unset>}\"\n"
            "printf 'synchronize_local_mapping=%s\\n' \"${ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING-<unset>}\"\n"
            "printf 'local_mapping_idle_timeout_sec=%s\\n' \"${ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC-<unset>}\"\n"
            "printf 'synchronize_loop_closing=%s\\n' \"${ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING-<unset>}\"\n"
            "printf 'loop_closing_idle_timeout_sec=%s\\n' \"${ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC-<unset>}\"\n"
            "printf 'deterministic_background_gate=%s\\n' \"${ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE-<unset>}\"\n"
            "printf 'export_online_trajectory=%s\\n' \"${ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY-<unset>}\"\n"
            "printf 'viewer=%s\\n' \"${ORB_SLAM3_USE_VIEWER-<unset>}\"\n"
            "awk '$1 == \"Cpus_allowed_list:\" {print \"effective_cpu_affinity=\" $2}' /proc/self/status\n"
            "printf 'personality=%s\\n' \"$(cat /proc/self/personality)\"\n"
            "if [[ -n \"${ORB_SLAM3_SEED_AUDIT_DIR-}\" ]]; then\n"
            "  mkdir -p \"$ORB_SLAM3_SEED_AUDIT_DIR\"\n"
            "  for artifact in seed_events.csv seed_mappoint_summary.csv seed_lineages.csv; do\n"
            "    if [[ \"${FAKE_AUDIT_OMIT-}\" != \"$artifact\" ]]; then\n"
            "      printf 'header\\n' > \"$ORB_SLAM3_SEED_AUDIT_DIR/$artifact\"\n"
            "    fi\n"
            "  done\n"
            "  if [[ \"${FAKE_AUDIT_OMIT-}\" != seed_summary.json ]]; then\n"
            "    audit_output_directory=\"${FAKE_AUDIT_OUTPUT_DIRECTORY-$ORB_SLAM3_SEED_AUDIT_DIR}\"\n"
            "    printf '{\"complete\":%s,\"output_directory\":\"%s\"}\\n' \\\n"
            "      \"${FAKE_AUDIT_COMPLETE-true}\" \"$audit_output_directory\" \\\n"
            "      > \"$ORB_SLAM3_SEED_AUDIT_DIR/seed_summary.json\"\n"
            "  fi\n"
            "fi\n"
            "if [[ \"${ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY-0}\" == 1 && \"${FAKE_ONLINE_TRAJECTORY_OMIT-0}\" != 1 ]]; then\n"
            "  trajectory_name=\"${!#}\"\n"
            "  printf '100 0 0 0 0 0 0 1\\n' > \"online_f_${trajectory_name}.txt\"\n"
            "fi\n",
            encoding="ascii",
        )
        binary.chmod(0o755)
        self.library = self.orb_root / "lib" / "libORB_SLAM3.so"
        self.library.parent.mkdir()
        self.library.write_text("fixture library\n", encoding="ascii")
        self.audit_source = self.orb_root / "src" / "ExternalSeedAudit.cc"
        self.audit_source.parent.mkdir()
        self.audit_source.write_text("// fixture audit source\n", encoding="ascii")
        self.mechanism_sources = (
            "include/ORBextractor.h",
            "include/Frame.h",
            "include/KeyFrame.h",
            "include/Optimizer.h",
            "src/ORBextractor.cc",
            "src/Frame.cc",
            "src/KeyFrame.cc",
            "src/Optimizer.cc",
        )
        for relative_path in self.mechanism_sources:
            source = self.orb_root / relative_path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f"// fixture {relative_path}\n", encoding="ascii")
        vocabulary = self.orb_root / "Vocabulary" / "ORBvoc.txt"
        vocabulary.parent.mkdir()
        vocabulary.write_text("vocabulary\n", encoding="ascii")

        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        self.times = self.root / "times.txt"
        self.times.write_text("100\n", encoding="ascii")
        self.config = self.root / "config.yaml"
        self.config.write_text("config\n", encoding="ascii")
        self.full_seeds = self.root / "full.txt"
        self.full_seeds.write_text("100 1 2 7 0.8\n", encoding="ascii")
        self.drop_seeds = self.root / "drop.txt"
        self.drop_seeds.write_text(
            "# timestamp_ns p_u p_v feature_id quality\n", encoding="ascii"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_triplet(
        self,
        output: Path,
        audit: str | None = None,
        *,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ORB_ROOT"] = str(self.orb_root)
        env["ORB_SLAM3_LIBRARY_PATH"] = str(self.library)
        env.pop("ORB_SLAM3_ENABLE_SEED_AUDIT", None)
        env["ORB_SLAM3_SEED_AUDIT_DIR"] = str(self.root / "inherited_audit")
        env["ORB_SLAM3_EXTERNAL_SEED_AUDIT_DIR"] = str(
            self.root / "inherited_compat_audit"
        )
        env["ORB_SLAM3_EXTERNAL_SEED_AUDIT"] = "1"
        env["ORB_SLAM3_EXTERNAL_SEED_AUDIT_MAX_EVENTS"] = "999"
        env.pop("ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE", None)
        env.pop("ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE", None)
        if audit is not None:
            env["ORB_SLAM3_ENABLE_SEED_AUDIT"] = audit
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                "bash",
                str(RUNNER),
                str(self.dataset),
                str(self.times),
                str(self.config),
                str(self.full_seeds),
                str(self.drop_seeds),
                str(output),
                "fixture",
                "1",
                "1",
            ],
            check=check,
            text=True,
            capture_output=True,
            env=env,
        )

    def test_legacy_arguments_keep_layout_and_audit_disabled(self) -> None:
        output = self.root / "legacy_runs"
        self.run_triplet(output)

        self.assertEqual(
            {path.name for path in output.iterdir()},
            {"orb_only_r1", "drop_r1", "full_r1"},
        )
        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            self.assertFalse((run_dir / "instrumentation").exists())
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["seed_audit_enabled"], "0")
            self.assertEqual(manifest["seed_audit_dir"], "")
            self.assertEqual(manifest["external_lineage_bridge_enabled"], "0")
            self.assertEqual(manifest["external_lineage_min_quality"], "0.0")
            self.assertEqual(
                manifest["external_lineage_max_projection_error_px"], "4.0"
            )
            self.assertEqual(
                manifest["external_lineage_max_descriptor_distance"], "100"
            )
            self.assertEqual(manifest["external_lineage_cull_grace_keyframes"], "0")
            self.assertEqual(manifest["external_lineage_max_assisted_matches"], "0")
            self.assertEqual(
                manifest["external_lineage_max_assisted_matches_requested"], "0"
            )
            self.assertEqual(manifest["external_lineage_native_birth_only"], "0")
            self.assertEqual(
                manifest["external_lineage_native_birth_only_requested"], "0"
            )
            self.assertEqual(
                manifest["external_lineage_quarantine_on_outlier"], "0"
            )
            self.assertEqual(
                manifest["external_lineage_quarantine_on_outlier_requested"], "0"
            )
            self.assertEqual(manifest["synchronize_local_mapping"], "0")
            self.assertEqual(manifest["local_mapping_idle_timeout_sec"], "60")
            self.assertEqual(manifest["synchronize_loop_closing"], "0")
            self.assertEqual(manifest["loop_closing_idle_timeout_sec"], "60")
            self.assertEqual(manifest["deterministic_background_gate"], "0")
            self.assertEqual(manifest["disable_aslr"], "0")
            self.assertEqual(manifest["export_online_trajectory"], "0")
            self.assertEqual(manifest["online_trajectory_file"], "")
            self.assertIn("audit=<unset>", (run_dir / "orbslam3_run.log").read_text())
            log_text = (run_dir / "orbslam3_run.log").read_text()
            self.assertIn("audit_enable=<unset>", log_text)
            self.assertIn("compat_audit_dir=<unset>", log_text)
            self.assertIn("compat_audit_enable=<unset>", log_text)
            self.assertIn("compat_audit_capacity=<unset>", log_text)
            self.assertIn("lineage_bridge=0", log_text)
            self.assertIn("lineage_min_quality=0.0", log_text)
            self.assertIn("lineage_max_projection_error=4.0", log_text)
            self.assertIn("lineage_max_descriptor_distance=100", log_text)
            self.assertIn("lineage_cull_grace_keyframes=0", log_text)
            self.assertIn("lineage_max_assisted_matches=0", log_text)
            self.assertIn("lineage_native_birth_only=0", log_text)
            self.assertIn("lineage_quarantine_on_outlier=0", log_text)
            self.assertIn("synchronize_local_mapping=0", log_text)
            self.assertIn("local_mapping_idle_timeout_sec=60", log_text)
            self.assertIn("synchronize_loop_closing=0", log_text)
            self.assertIn("loop_closing_idle_timeout_sec=60", log_text)
            self.assertIn("deterministic_background_gate=0", log_text)
            self.assertIn("export_online_trajectory=0", log_text)

        orb_log = (output / "orb_only_r1" / "orbslam3_run.log").read_text()
        self.assertIn("seed=<unset>", orb_log)

    def test_enabled_audit_passes_unique_run_directory_and_hashes(self) -> None:
        output = self.root / "audit_runs"
        self.run_triplet(output, audit="1")

        runner_sha256 = hashlib.sha256(RUNNER.read_bytes()).hexdigest()
        vocabulary = self.orb_root / "Vocabulary" / "ORBvoc.txt"
        vocabulary_sha256 = hashlib.sha256(vocabulary.read_bytes()).hexdigest()
        library_sha256 = hashlib.sha256(self.library.read_bytes()).hexdigest()
        audit_source_sha256 = hashlib.sha256(self.audit_source.read_bytes()).hexdigest()
        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            audit_dir = run_dir / "instrumentation"
            self.assertTrue(audit_dir.is_dir())
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["seed_audit_enabled"], "1")
            self.assertEqual(manifest["seed_audit_dir"], str(audit_dir))
            runtime_audit_dir = Path(manifest["runtime_seed_audit_dir"])
            self.assertEqual(runtime_audit_dir.resolve(), audit_dir.resolve())
            self.assertEqual(manifest["runner_sha256"], runner_sha256)
            self.assertEqual(manifest["vocabulary_sha256"], vocabulary_sha256)
            self.assertEqual(manifest["liborbslam3_path"], str(self.library.resolve()))
            self.assertEqual(manifest["liborbslam3_sha256"], library_sha256)
            self.assertEqual(manifest["liborbslam3_resolution"], "override")
            self.assertEqual(
                manifest["external_seed_audit_source_path"],
                str(self.audit_source.resolve()),
            )
            self.assertEqual(
                manifest["external_seed_audit_source_sha256"], audit_source_sha256
            )
            provenance_dir = run_dir / "provenance"
            provenance_manifest = provenance_dir / "snapshot_sha256.txt"
            self.assertEqual(manifest["provenance_dir"], str(provenance_dir))
            self.assertEqual(
                manifest["provenance_manifest"], str(provenance_manifest)
            )
            self.assertEqual(
                manifest["provenance_manifest_sha256"],
                hashlib.sha256(provenance_manifest.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                hashlib.sha256(
                    (provenance_dir / "runtime" / "mono_euroc_old").read_bytes()
                ).hexdigest(),
                manifest["binary_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(
                    (provenance_dir / "runtime" / "libORB_SLAM3.so").read_bytes()
                ).hexdigest(),
                manifest["liborbslam3_sha256"],
            )
            self.assertTrue(
                (
                    provenance_dir
                    / "sources"
                    / "src"
                    / "ExternalSeedAudit.cc"
                ).is_file()
            )
            snapshot_text = provenance_manifest.read_text()
            self.assertIn("./runtime/mono_euroc_old", snapshot_text)
            self.assertIn("./runtime/libORB_SLAM3.so", snapshot_text)
            self.assertIn("./sources/src/ExternalSeedAudit.cc", snapshot_text)
            for relative_path in self.mechanism_sources:
                self.assertIn(f"./sources/{relative_path}", snapshot_text)
            log_text = (run_dir / "orbslam3_run.log").read_text()
            self.assertIn(f"audit={runtime_audit_dir}", log_text)
            self.assertIn("audit_enable=1", log_text)
            self.assertIn("compat_audit_dir=<unset>", log_text)
            self.assertIn("compat_audit_enable=<unset>", log_text)
            self.assertIn("compat_audit_capacity=<unset>", log_text)
            self.assertIn("viewer=0", log_text)

        self.assertIn(
            f"seed={self.drop_seeds.resolve()}",
            (output / "drop_r1" / "orbslam3_run.log").read_text(),
        )
        self.assertIn(
            f"seed={self.full_seeds.resolve()}",
            (output / "full_r1" / "orbslam3_run.log").read_text(),
        )

    def test_single_cpu_affinity_is_validated_recorded_and_applied(self) -> None:
        cpu = min(os.sched_getaffinity(0))
        output = self.root / "single_cpu_runs"

        self.run_triplet(
            output,
            extra_env={"ORB_SLAM3_CPU_AFFINITY": str(cpu)},
        )

        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["cpu_affinity"], str(cpu))
            self.assertEqual(manifest["scheduler_mode"], "single_cpu")
            self.assertIn(
                f"effective_cpu_affinity={cpu}",
                (run_dir / "orbslam3_run.log").read_text(),
            )

    def test_local_mapping_synchronization_is_recorded_and_passed(self) -> None:
        output = self.root / "synchronized_runs"

        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING": "1",
                "ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC": "30.5",
                "ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING": "1",
                "ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC": "31.5",
                "ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE": "1",
            },
        )

        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["synchronize_local_mapping"], "1")
            self.assertEqual(manifest["local_mapping_idle_timeout_sec"], "30.5")
            self.assertEqual(manifest["synchronize_loop_closing"], "1")
            self.assertEqual(manifest["loop_closing_idle_timeout_sec"], "31.5")
            self.assertEqual(manifest["deterministic_background_gate"], "1")
            log_text = (run_dir / "orbslam3_run.log").read_text()
            self.assertIn("synchronize_local_mapping=1", log_text)
            self.assertIn("local_mapping_idle_timeout_sec=30.5", log_text)
            self.assertIn("synchronize_loop_closing=1", log_text)
            self.assertIn("loop_closing_idle_timeout_sec=31.5", log_text)
            self.assertIn("deterministic_background_gate=1", log_text)

    def test_aslr_disable_is_validated_recorded_and_applied(self) -> None:
        output = self.root / "aslr_disabled_runs"

        self.run_triplet(
            output,
            extra_env={"ORB_SLAM3_DISABLE_ASLR": "1"},
        )

        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["disable_aslr"], "1")
            self.assertEqual(manifest["machine_arch"], os.uname().machine)
            self.assertIn(
                "personality=00040000",
                (run_dir / "orbslam3_run.log").read_text(),
            )
            self.assertIn(
                "runtime_personality=00040000",
                (run_dir / "orbslam3_run.log").read_text(),
            )

    def test_lineage_bridge_parameters_are_validated_recorded_and_passed(self) -> None:
        output = self.root / "lineage_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY": "0.65",
                "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX": "3.5",
                "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE": "96",
                "ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES": "12",
            },
        )

        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["external_lineage_bridge_enabled"], "1")
            self.assertEqual(manifest["external_lineage_min_quality"], "0.65")
            self.assertEqual(
                manifest["external_lineage_max_projection_error_px"], "3.5"
            )
            self.assertEqual(
                manifest["external_lineage_max_descriptor_distance"], "96"
            )
            self.assertEqual(manifest["external_lineage_cull_grace_keyframes"], "12")
            log_text = (run_dir / "orbslam3_run.log").read_text()
            self.assertIn("lineage_bridge=1", log_text)
            self.assertIn("lineage_min_quality=0.65", log_text)
            self.assertIn("lineage_max_projection_error=3.5", log_text)
            self.assertIn("lineage_max_descriptor_distance=96", log_text)
            self.assertIn("lineage_cull_grace_keyframes=12", log_text)

    def test_online_trajectory_export_is_recorded_passed_and_required(self) -> None:
        output = self.root / "online_trajectory_runs"
        self.run_triplet(
            output,
            extra_env={"ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY": "1"},
        )

        for role in ("orb_only", "drop", "full"):
            run_dir = output / f"{role}_r1"
            trajectory = run_dir / f"online_f_fixture_{role}_r1.txt"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(manifest["export_online_trajectory"], "1")
            self.assertEqual(manifest["online_trajectory_file"], str(trajectory))
            self.assertTrue(trajectory.stat().st_size > 0)
            self.assertIn(
                "export_online_trajectory=1",
                (run_dir / "orbslam3_run.log").read_text(),
            )

        failed = self.run_triplet(
            self.root / "missing_online_trajectory_runs",
            check=False,
            extra_env={
                "ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY": "1",
                "FAKE_ONLINE_TRAJECTORY_OMIT": "1",
            },
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("missing or empty online trajectory", failed.stderr)

    def test_assisted_match_dose_has_unbounded_closest_control(self) -> None:
        output = self.root / "dose_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES": "8",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_unbounded full"
                ),
            },
        )

        self.assertEqual(
            {path.name for path in output.iterdir()},
            {
                "orb_only_r1",
                "drop_r1",
                "full_bridge_off_r1",
                "full_unbounded_r1",
                "full_r1",
            },
        )
        expected_dose = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "0",
            "full": "8",
        }
        for role, dose in expected_dose.items():
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(
                manifest["external_lineage_max_assisted_matches"], dose
            )
            self.assertEqual(
                manifest["external_lineage_max_assisted_matches_requested"], "8"
            )
            self.assertIn(
                f"lineage_max_assisted_matches={dose}",
                (run_dir / "orbslam3_run.log").read_text(),
            )
        self.assertIn(
            f"seed={self.full_seeds.resolve()}",
            (output / "full_unbounded_r1" / "orbslam3_run.log").read_text(),
        )

    def test_native_birth_only_has_unbounded_closest_control(self) -> None:
        output = self.root / "native_birth_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY": "1",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_unbounded full"
                ),
            },
        )

        expected_native_birth = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "0",
            "full": "1",
        }
        for role, enabled in expected_native_birth.items():
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(
                manifest["external_lineage_native_birth_only"], enabled
            )
            self.assertEqual(
                manifest["external_lineage_native_birth_only_requested"], "1"
            )
            self.assertIn(
                f"lineage_native_birth_only={enabled}",
                (run_dir / "orbslam3_run.log").read_text(),
            )

    def test_outlier_quarantine_has_unbounded_closest_control(self) -> None:
        output = self.root / "quarantine_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER": "1",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_unbounded full"
                ),
            },
        )

        expected_quarantine = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "1",
            "full": "1",
        }
        expected_enforce = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "0",
            "full": "1",
        }
        for role, enabled in expected_quarantine.items():
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(
                manifest["external_lineage_quarantine_on_outlier"], enabled
            )
            self.assertEqual(
                manifest["external_lineage_quarantine_on_outlier_requested"], "1"
            )
            self.assertIn(
                f"lineage_quarantine_on_outlier={enabled}",
                (run_dir / "orbslam3_run.log").read_text(),
            )
            self.assertEqual(
                manifest["external_lineage_quarantine_enforce"],
                expected_enforce[role],
            )
            self.assertIn(
                f"lineage_quarantine_enforce={expected_enforce[role]}",
                (run_dir / "orbslam3_run.log").read_text(),
            )

    def test_terminal_quarantine_is_candidate_only(self) -> None:
        output = self.root / "terminal_quarantine_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE": "1",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_unbounded full"
                ),
            },
        )

        expected_terminal = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "1",
            "full": "1",
        }
        for role, enabled in expected_terminal.items():
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(
                manifest["external_lineage_terminal_quarantine"], enabled
            )
            self.assertEqual(
                manifest["external_lineage_terminal_quarantine_requested"], "1"
            )
            self.assertIn(
                f"lineage_terminal_quarantine={enabled}",
                (run_dir / "orbslam3_run.log").read_text(),
            )
            expected_enforce = "1" if role == "full" else "0"
            self.assertEqual(
                manifest["external_lineage_quarantine_enforce"],
                expected_enforce,
            )

    def test_pre_kf_outlier_purge_has_unbounded_shadow(self) -> None:
        output = self.root / "pre_kf_outlier_purge_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE": "1",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_unbounded full"
                ),
            },
        )

        expected_scan = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "1",
            "full": "1",
        }
        expected_enforce = {
            "orb_only": "0",
            "drop": "0",
            "full_bridge_off": "0",
            "full_unbounded": "0",
            "full": "1",
        }
        for role in expected_scan:
            run_dir = output / f"{role}_r1"
            manifest = parse_manifest(run_dir / "run_manifest.txt")
            self.assertEqual(
                manifest["external_lineage_pre_kf_outlier_purge"],
                expected_scan[role],
            )
            self.assertEqual(
                manifest["external_lineage_pre_kf_outlier_purge_requested"], "1"
            )
            self.assertEqual(
                manifest["external_lineage_pre_kf_outlier_purge_enforce"],
                expected_enforce[role],
            )
            self.assertEqual(
                manifest[
                    "external_lineage_pre_kf_outlier_purge_enforce_requested"
                ],
                "1",
            )
            log_text = (run_dir / "orbslam3_run.log").read_text()
            self.assertIn(
                f"lineage_pre_kf_outlier_purge={expected_scan[role]}", log_text
            )
            self.assertIn(
                "lineage_pre_kf_outlier_purge_enforce="
                f"{expected_enforce[role]}",
                log_text,
            )

        for role in ("full_unbounded", "full"):
            manifest = parse_manifest(output / f"{role}_r1" / "run_manifest.txt")
            self.assertEqual(manifest["external_lineage_native_birth_only"], "0")
            self.assertEqual(
                manifest["external_lineage_quarantine_on_outlier"], "0"
            )
            self.assertEqual(
                manifest["external_lineage_terminal_quarantine"], "0"
            )

    def test_optional_lineage_ablation_roles_use_full_seed_and_expected_gates(self) -> None:
        output = self.root / "four_arm_runs"
        self.run_triplet(
            output,
            extra_env={
                "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "1",
                "ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES": "16",
                "ORB_SLAM3_ROLE_ORDER": (
                    "orb_only drop full_bridge_off full_lineage_no_grace full"
                ),
            },
        )

        self.assertEqual(
            {path.name for path in output.iterdir()},
            {
                "orb_only_r1",
                "drop_r1",
                "full_bridge_off_r1",
                "full_lineage_no_grace_r1",
                "full_r1",
            },
        )
        bridge_off = output / "full_bridge_off_r1"
        no_grace = output / "full_lineage_no_grace_r1"
        bridge_on = output / "full_r1"
        self.assertEqual(
            parse_manifest(bridge_off / "run_manifest.txt")[
                "external_lineage_bridge_enabled"
            ],
            "0",
        )
        self.assertEqual(
            parse_manifest(no_grace / "run_manifest.txt")[
                "external_lineage_bridge_enabled"
            ],
            "1",
        )
        self.assertEqual(
            parse_manifest(bridge_on / "run_manifest.txt")[
                "external_lineage_bridge_enabled"
            ],
            "1",
        )
        self.assertEqual(
            parse_manifest(bridge_off / "run_manifest.txt")[
                "external_lineage_cull_grace_keyframes"
            ],
            "0",
        )
        self.assertEqual(
            parse_manifest(no_grace / "run_manifest.txt")[
                "external_lineage_cull_grace_keyframes"
            ],
            "0",
        )
        self.assertEqual(
            parse_manifest(bridge_on / "run_manifest.txt")[
                "external_lineage_cull_grace_keyframes"
            ],
            "16",
        )
        self.assertIn(
            f"seed={self.full_seeds.resolve()}",
            (bridge_off / "orbslam3_run.log").read_text(),
        )
        self.assertIn("lineage_bridge=0", (bridge_off / "orbslam3_run.log").read_text())
        self.assertIn("lineage_cull_grace_keyframes=0", (no_grace / "orbslam3_run.log").read_text())
        self.assertIn("lineage_bridge=1", (bridge_on / "orbslam3_run.log").read_text())
        self.assertIn("lineage_cull_grace_keyframes=16", (bridge_on / "orbslam3_run.log").read_text())

    def test_rejects_invalid_lineage_bridge_parameters(self) -> None:
        cases = (
            ("bridge", {"ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE": "yes"}),
            ("quality", {"ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY": "1.1"}),
            (
                "projection",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX": "0"},
            ),
            (
                "descriptor",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE": "101"},
            ),
            (
                "cull_grace",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES": "101"},
            ),
            (
                "assisted_match_dose",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES": "100001"},
            ),
            (
                "native_birth_only",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY": "yes"},
            ),
            (
                "quarantine_on_outlier",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER": "yes"},
            ),
            (
                "terminal_quarantine",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE": "yes"},
            ),
            (
                "terminal_quarantine_requires_outlier",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE": "1"},
            ),
            (
                "quarantine_enforce",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE": "yes"},
            ),
            (
                "quarantine_enforce_requires_outlier",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE": "1"},
            ),
            (
                "pre_kf_outlier_purge",
                {"ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE": "yes"},
            ),
            (
                "pre_kf_outlier_purge_enforce",
                {
                    "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE": "yes"
                },
            ),
            (
                "pre_kf_outlier_purge_enforce_requires_scan",
                {
                    "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE": "1"
                },
            ),
            ("cpu_affinity", {"ORB_SLAM3_CPU_AFFINITY": "0-1"}),
            ("sync_local_mapping", {"ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING": "yes"}),
            (
                "local_mapping_timeout",
                {"ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC": "0"},
            ),
            (
                "sync_loop_closing",
                {"ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING": "yes"},
            ),
            (
                "sync_loop_requires_local",
                {"ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING": "1"},
            ),
            (
                "loop_closing_timeout",
                {"ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC": "0"},
            ),
            (
                "deterministic_gate",
                {"ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE": "yes"},
            ),
            (
                "deterministic_gate_requires_barriers",
                {"ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE": "1"},
            ),
            ("disable_aslr", {"ORB_SLAM3_DISABLE_ASLR": "yes"}),
            (
                "export_online_trajectory",
                {"ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY": "yes"},
            ),
        )
        for name, extra_env in cases:
            with self.subTest(name=name):
                result = self.run_triplet(
                    self.root / f"invalid_{name}", check=False, extra_env=extra_env
                )
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_stale_run_directory_before_starting_any_role(self) -> None:
        output = self.root / "stale_runs"
        stale_run = output / "full_r1"
        stale_run.mkdir(parents=True)
        (stale_run / "old_result.txt").write_text("stale\n", encoding="ascii")

        result = self.run_triplet(output, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing non-empty run directory", result.stderr)
        self.assertFalse((output / "orb_only_r1").exists())
        self.assertFalse((output / "drop_r1").exists())
        self.assertEqual((stale_run / "old_result.txt").read_text(), "stale\n")

    def test_enabled_audit_rejects_missing_artifact(self) -> None:
        output = self.root / "missing_artifact_runs"

        result = self.run_triplet(
            output,
            audit="1",
            check=False,
            extra_env={"FAKE_AUDIT_OMIT": "seed_lineages.csv"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing seed audit artifact", result.stderr)
        self.assertFalse((output / "drop_r1").exists())

    def test_enabled_audit_rejects_incomplete_or_misdirected_summary(self) -> None:
        cases = (
            (
                "incomplete",
                {"FAKE_AUDIT_COMPLETE": "false"},
                "seed audit summary is incomplete",
            ),
            (
                "misdirected",
                {"FAKE_AUDIT_OUTPUT_DIRECTORY": str(self.root / "wrong_audit")},
                "seed audit output_directory mismatch",
            ),
        )
        for name, extra_env, expected_error in cases:
            with self.subTest(name=name):
                output = self.root / f"{name}_summary_runs"
                result = self.run_triplet(
                    output, audit="1", check=False, extra_env=extra_env
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertFalse((output / "drop_r1").exists())

    def test_manifest_uses_ldd_resolution_and_rejects_override_mismatch(self) -> None:
        tools_dir = self.root / "tools"
        tools_dir.mkdir()
        fake_ldd = tools_dir / "ldd"
        fake_ldd.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'libORB_SLAM3.so => %s (0x1)\\n' \"$FAKE_LDD_LIBRARY\"\n",
            encoding="ascii",
        )
        fake_ldd.chmod(0o755)
        common_env = {
            "PATH": f"{tools_dir}:{os.environ['PATH']}",
            "FAKE_LDD_LIBRARY": str(self.library),
        }

        output = self.root / "ldd_runs"
        self.run_triplet(output, extra_env=common_env)
        manifest = parse_manifest(output / "orb_only_r1" / "run_manifest.txt")
        self.assertEqual(manifest["liborbslam3_resolution"], "ldd")
        self.assertEqual(manifest["liborbslam3_path"], str(self.library.resolve()))

        other_library = self.root / "other" / "libORB_SLAM3.so"
        other_library.parent.mkdir()
        other_library.write_text("wrong library\n", encoding="ascii")
        mismatch_env = {
            **common_env,
            "ORB_SLAM3_LIBRARY_PATH": str(other_library),
        }
        result = self.run_triplet(
            self.root / "mismatch_runs", check=False, extra_env=mismatch_env
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disagrees with ldd", result.stderr)

    def test_elf_binary_cannot_use_library_override_as_ldd_fallback(self) -> None:
        binary = self.orb_root / "Examples_old" / "Monocular" / "mono_euroc_old"
        binary.write_bytes(b"\x7fELFfixture")
        binary.chmod(0o755)

        result = self.run_triplet(self.root / "elf_override_runs", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fallback for ELF binary", result.stderr)


if __name__ == "__main__":
    unittest.main()
