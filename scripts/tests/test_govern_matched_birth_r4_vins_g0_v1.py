from __future__ import annotations

from contextlib import contextmanager, ExitStack
import copy
import csv
import hashlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from scripts import govern_matched_birth_r4_vins_g0_v1 as g


HASH = "a" * 64


def spawn_signal_guard(
    *, process_started: bool = True, received: list[str] | None = None
) -> dict[str, object]:
    return {
        "policy": g._spawn_signal_policy(),
        "prior_target_mask": [],
        "prior_handlers": g._spawn_signal_policy()["required_prior_handlers"],
        "install_transition_mask_applied": True,
        "handlers_installed_before_popen": True,
        "spawn_target_mask": [],
        "pid_captured_while_handlers_installed": process_started,
        "received_signals": [] if received is None else list(received),
        "cleanup_mode_before_restore": True,
        "child_reaped_before_restore": True,
        "restore_transition_mask_applied": True,
        "handlers_restored": True,
        "post_restore_target_mask": [],
    }


def child_target_signal_mask() -> dict[str, object]:
    return {
        "query": "pthread_sigmask(SIG_BLOCK,EMPTY_SET)_NO_STATE_CHANGE",
        "target_signals": [
            {"name": "SIGHUP", "number": 1},
            {"name": "SIGINT", "number": 2},
            {"name": "SIGTERM", "number": 15},
        ],
        "blocked_target_signals": [],
    }


def record(path: object, digest: str = HASH, size: int = 7) -> dict[str, object]:
    return {"path": os.fspath(path), "sha256": digest, "size_bytes": size}


def fake_freeze() -> dict[str, object]:
    inputs = {name: record(path) for name, path in g.INPUTS.items()}
    helpers = {name: record(path) for name, path in g.HELPERS.items()}
    result: dict[str, object] = {
        "freeze_hash": "f" * 64,
        "python_interpreter": record(g.PYTHON),
        "input_records": inputs,
        "helper_code_closure": helpers,
        "authorized_role_argv": {
            role: g.canonical_role_argv(role) for role in g.ROLE_NAMES
        },
        "authorized_environment_templates": {
            role: g._environment_template(role) for role in g.ROLE_NAMES
        },
        "expected_runtime_closure": {"runtime_receipt": {"fixture": True}},
    }
    return result


def aliases(role: str) -> dict[str, str]:
    keys = [
        os.fspath(g.PYTHON),
        os.fspath(g.BOOTSTRAP),
        os.fspath(g.RAW_BAG),
        os.fspath(g.CONFIG),
        os.fspath(g.GFTT_VIO),
        os.fspath(g.XFEAT_VIO),
        os.fspath(g.OUTPUT / role),
        "${EPOCH_WRAPPER_PROCFD}",
        "${EVALUATOR_BASE_PROCFD}",
        "${TRAJECTORY_CORE_PROCFD}",
        "${ROLE_OUTPUT_DIRFD}",
    ]
    values = {key: f"/proc/self/fd/{30 + index}" for index, key in enumerate(keys)}
    values["${ROLE_OUTPUT_DIRFD}"] = values[os.fspath(g.OUTPUT / role)]
    return values


def process_receipt(role: str, freeze: dict[str, object]) -> dict[str, object]:
    mapping = aliases(role)
    canonical = freeze["authorized_role_argv"][role]
    assert isinstance(canonical, list)
    value: dict[str, object] = {
        "schema_version": g.PROCESS_SCHEMA,
        "status": "COMPLETED_RC0",
        "role": role,
        "pid": 12345,
        "process_started_before_wait": True,
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "timeout_seconds": g.PROCESS_TIMEOUT_SECONDS,
        "timed_out": False,
        "return_code": 0,
        "termination_signal": None,
        "classification": "EXITED_RC0",
        "wait_error": None,
        "cleanup_errors": [],
        "child_reaped": True,
        "spawn_signal_guard": spawn_signal_guard(),
        "stdout": {"sha256": HASH, "size_bytes": 0},
        "stderr": {"sha256": HASH, "size_bytes": 0},
        "authorized_canonical_argv": canonical,
        "actual_procfd_argv": g._materialize_strings(canonical, mapping),
        "actual_procfd_aliases": mapping,
        "actual_procfd_binding_records": g._procfd_binding_records(
            role, mapping, freeze
        ),
        "pass_fd_numbers": g._procfd_numbers(mapping, label="fixture"),
        "authorized_environment_template": freeze[
            "authorized_environment_templates"
        ][role],
        "actual_environment_sha256": hashlib.sha256(
            g._canonical_json_bytes(
                g._materialize_environment(
                    freeze["authorized_environment_templates"][role], mapping
                )
            )
        ).hexdigest(),
        "freeze_hash": freeze["freeze_hash"],
        "launch_intent_hash": "e" * 64,
        "process_receipt_hash": "0" * 64,
    }
    value["process_receipt_hash"] = g.p07gov.canonical_json_hash(
        value, "process_receipt_hash"
    )
    return value


def launch_intent(role: str, freeze: dict[str, object]) -> dict[str, object]:
    mapping = aliases(role)
    canonical = freeze["authorized_role_argv"][role]
    assert isinstance(canonical, list)
    environment = g._materialize_environment(
        freeze["authorized_environment_templates"][role], mapping
    )
    return g._launch_intent(
        role,
        g._materialize_strings(canonical, mapping),
        environment,
        mapping,
        freeze,
    )


def outer_command(action: str = "check-start") -> list[str]:
    digest = hashlib.sha256(Path(g._OUTER_SCRIPT).read_bytes()).hexdigest()
    return g._outer_formal_command(action, digest)


class ContractTests(unittest.TestCase):
    def test_canonical_argv_is_isolated_no_bytecode_no_evo(self) -> None:
        for role in g.ROLE_NAMES:
            argv = g.canonical_role_argv(role)
            self.assertEqual(argv[:4], [str(g.PYTHON), "-I", "-B", str(g.BOOTSTRAP)])
            self.assertEqual(argv.count("--arm"), 2)
            self.assertEqual(argv.count("--arm-config"), 2)
            self.assertNotIn("--run-evo", argv)
            joined = " ".join(argv)
            for forbidden in ("vins_node", "run_aqualoc", "export_matched"):
                self.assertNotIn(forbidden, joined)

    def test_environment_is_exact_sanitized_and_has_no_user_local(self) -> None:
        expected_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        for role in g.ROLE_NAMES:
            environment = g._environment_template(role)
            self.assertEqual(environment["PATH"], expected_path)
            self.assertNotIn("/home/ma/.local", json.dumps(environment))
            self.assertNotIn("PYTHONPATH", environment)
            self.assertNotIn("PYTHONHOME", environment)

    def test_full_reference_protocol_and_post_result_claim_boundary(self) -> None:
        protocol = g._protocol()
        self.assertEqual(protocol["window_start_ns"], g.WINDOW_START_NS)
        self.assertEqual(protocol["window_end_ns"], g.WINDOW_END_NS)
        self.assertEqual(protocol["expected_uniform_grid_count"], 90)
        self.assertEqual(protocol["reference"], f"{g.RAW_BAG}:{g.REFERENCE_TOPIC}")
        self.assertFalse(g.OUTCOME_BOUNDARY["outcome_blind"])
        self.assertFalse(g.OUTCOME_BOUNDARY["confirmatory"])
        self.assertIn("POST_RESULT", g.PUBLICATION_TECHNICAL_BOUNDARY)

    def test_helper_and_vins_evidence_closure_is_explicit(self) -> None:
        self.assertEqual(
            set(g.HELPERS),
            {
                "governor", "child_bootstrap", "backend", "formal_io",
                "p07_governance", "backend_evaluation", "publisher", "runner",
                "epoch_wrapper", "evaluator_base", "trajectory_core", "vins_runner",
            },
        )
        for arm in ("xfeat", "gftt"):
            for leaf in (
                "replay_manifest_txt", "vins_env_manifest_txt",
                "aqualoc_archaeo02_pinhole_yaml",
                "vins_aqualoc_archaeo_external_yaml", "vins_log",
            ):
                self.assertIn(f"{arm}_{leaf}", g.INPUTS)
        self.assertNotIn("ape", " ".join(g.INPUTS).lower())

    def test_only_consumed_scientific_inputs_are_execution_memfds(self) -> None:
        self.assertEqual(
            g.EXECUTION_INPUT_KEYS,
            ("reference_bag", "config", "gftt_vio", "xfeat_vio"),
        )
        source = inspect.getsource(g._sealed_execution_inputs)
        self.assertIn("for role in EXECUTION_INPUT_KEYS", source)
        self.assertNotIn("sorted(INPUTS)", source)

    def test_hard_live_authority_and_vins_provenance_pass(self) -> None:
        g._static_authority_check()

    def test_raw_bag_config_and_reference_schedule_are_hard_cross_bound(self) -> None:
        self.assertEqual((g.RAW_BAG_SHA256, g.RAW_BAG_SIZE),
                         ("eebd45439e76c461e58a2a1d6321f3fcb82dbcf57ea4093929548c9620e63a83", 449056538))
        self.assertEqual((g.CONFIG_SHA256, g.CONFIG_SIZE),
                         ("a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1", 415))
        seal = g._load_json_static(g.CORRECTED_SEAL, "fixture corrected seal")
        fixed = {
            g.RAW_BAG: record(g.RAW_BAG, g.RAW_BAG_SHA256, g.RAW_BAG_SIZE),
            g.CONFIG: record(g.CONFIG, g.CONFIG_SHA256, g.CONFIG_SIZE),
            g.REFERENCE_BAG_MANIFEST: record(
                g.REFERENCE_BAG_MANIFEST, g.REFERENCE_BAG_MANIFEST_SHA256,
                g.REFERENCE_BAG_MANIFEST_SIZE,
            ),
            g.CONFIG_SEALED_AUTHORITY: record(
                g.CONFIG_SEALED_AUTHORITY, g.CONFIG_SEALED_AUTHORITY_SHA256,
                g.CONFIG_SEALED_AUTHORITY_SIZE,
            ),
        }
        with mock.patch.object(g, "_workspace_record", side_effect=lambda path, _label: fixed[Path(path)]):
            g._validate_scientific_input_authority(seal)
        for target in (g.RAW_BAG, g.CONFIG, g.REFERENCE_BAG_MANIFEST, g.CONFIG_SEALED_AUTHORITY):
            altered = copy.deepcopy(fixed)
            altered[target]["sha256"] = "b" * 64
            with self.subTest(target=target), mock.patch.object(
                g, "_workspace_record", side_effect=lambda path, _label: altered[Path(path)]
            ), self.assertRaises(g.GovernanceError):
                g._validate_scientific_input_authority(seal)

    def test_reference_manifest_topic_count_and_endpoints_are_strict(self) -> None:
        seal = g._load_json_static(g.CORRECTED_SEAL, "fixture corrected seal")
        manifest = g._load_json_static(g.REFERENCE_BAG_MANIFEST, "fixture manifest")
        authority = g._load_json_static(g.CONFIG_SEALED_AUTHORITY, "fixture config authority")
        fixed = {
            g.RAW_BAG: record(g.RAW_BAG, g.RAW_BAG_SHA256, g.RAW_BAG_SIZE),
            g.CONFIG: record(g.CONFIG, g.CONFIG_SHA256, g.CONFIG_SIZE),
            g.REFERENCE_BAG_MANIFEST: record(g.REFERENCE_BAG_MANIFEST, g.REFERENCE_BAG_MANIFEST_SHA256, g.REFERENCE_BAG_MANIFEST_SIZE),
            g.CONFIG_SEALED_AUTHORITY: record(g.CONFIG_SEALED_AUTHORITY, g.CONFIG_SEALED_AUTHORITY_SHA256, g.CONFIG_SEALED_AUTHORITY_SIZE),
        }
        for mutation in ("topic", "count", "first", "last", "config"):
            changed_manifest = copy.deepcopy(manifest)
            changed_authority = copy.deepcopy(authority)
            if mutation == "topic":
                changed_manifest["output"]["topic_counts"][g.REFERENCE_TOPIC] = None
            elif mutation == "count":
                changed_manifest["output"]["topic_counts"][g.REFERENCE_TOPIC] = 90
            elif mutation == "first":
                changed_manifest["output"]["topic_first_header_ns"][g.REFERENCE_TOPIC] += 1
            elif mutation == "last":
                changed_manifest["output"]["topic_last_header_ns"][g.REFERENCE_TOPIC] -= 1
            else:
                changed_authority["config"]["size_bytes"] = 414
            def load(path: Path, _label: str) -> dict[str, object]:
                return changed_manifest if Path(path) == g.REFERENCE_BAG_MANIFEST else changed_authority
            with self.subTest(mutation=mutation), mock.patch.object(
                g, "_workspace_record", side_effect=lambda path, _label: fixed[Path(path)]
            ), mock.patch.object(g, "_load_json_static", side_effect=load), self.assertRaises(g.GovernanceError):
                g._validate_scientific_input_authority(seal)

    def test_vins_provenance_hard_pins_every_scientific_evidence_leaf(self) -> None:
        expected_sizes = {
            "xfeat": {"vio_csv": 89021, "replay_manifest_txt": 488,
                       "vins_env_manifest_txt": 2255,
                       "aqualoc_archaeo02_pinhole_yaml": 357,
                       "vins_aqualoc_archaeo_external_yaml": 985,
                       "vins_log": 89793},
            "gftt": {"vio_csv": 89819, "replay_manifest_txt": 485,
                      "vins_env_manifest_txt": 2253,
                      "aqualoc_archaeo02_pinhole_yaml": 357,
                      "vins_aqualoc_archaeo_external_yaml": 984,
                      "vins_log": 98543},
        }
        self.assertEqual(
            {arm: {key: value[1] for key, value in rows.items()}
             for arm, rows in g.VINS_PROVENANCE_AUTHORITY.items()},
            expected_sizes,
        )
        for arm, rows in g.VINS_PROVENANCE_AUTHORITY.items():
            for key, (digest, size) in rows.items():
                with self.subTest(arm=arm, key=key):
                    self.assertRegex(digest, r"^[0-9a-f]{64}$")
                    self.assertGreater(size, 0)

    def test_vins_provenance_rejects_hard_pin_mutation_and_extra_environment_key(self) -> None:
        seal = g._load_json_static(g.CORRECTED_SEAL, "fixture corrected seal")
        original = g._workspace_record
        with mock.patch.object(
            g, "_workspace_record",
            side_effect=lambda path, label: (
                {**original(path, label), "sha256": "b" * 64}
                if Path(path) == g.XFEAT_VIO else original(path, label)
            ),
        ), self.assertRaises(g.GovernanceError):
            g._validate_vins_provenance(seal)
        original_parser = g._parse_key_value_lines
        with mock.patch.object(
            g, "_parse_key_value_lines",
            side_effect=lambda content, label: (
                {**original_parser(content, label), "EXTRA": "forbidden"}
                if label == "xfeat VINS env" else original_parser(content, label)
            ),
        ), self.assertRaises(g.GovernanceError):
            g._validate_vins_provenance(seal)

    def test_real_outer_cli_guard_enters_main_and_keeps_prefix_absent(self) -> None:
        prefix = Path(g._OUTER_PYCACHE_PREFIX)
        self.assertFalse(os.path.lexists(prefix))
        command = outer_command()
        process = subprocess.run(
            command,
            cwd=g.ROOT,
            env=dict(g._OUTER_ENVIRONMENT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"missing G0 freeze", process.stderr)
        self.assertNotIn(b"OUTER_GUARD_ERROR", process.stderr)
        self.assertFalse(os.path.lexists(prefix))

    def test_real_outer_cli_uses_structurally_uncreatable_pycache_prefix(self) -> None:
        prefix = Path(g._OUTER_PYCACHE_PREFIX)
        self.assertEqual(prefix.parent, Path("/dev/null"))
        devnull = os.lstat("/dev/null")
        self.assertTrue(stat.S_ISCHR(devnull.st_mode))
        self.assertEqual((devnull.st_uid, devnull.st_gid, stat.S_IMODE(devnull.st_mode)), (0, 0, 0o666))
        with self.assertRaises((NotADirectoryError, FileExistsError, OSError)):
            prefix.mkdir(mode=0o700)
        process = subprocess.run(
            outer_command(),
            cwd=g.ROOT,
            env=dict(g._OUTER_ENVIRONMENT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"missing G0 freeze", process.stderr)
        self.assertNotIn(b"OUTER_GUARD_ERROR", process.stderr)

    def test_real_outer_cli_rejects_extra_environment_and_missing_bytecode_flag(self) -> None:
        variants = [
            (
                outer_command(),
                {**g._OUTER_ENVIRONMENT, "EXTRA": "forbidden"},
            ),
            (
                [item for index, item in enumerate(outer_command()) if index != 2],
                dict(g._OUTER_ENVIRONMENT),
            ),
        ]
        for command, environment in variants:
            with self.subTest(command=command, extra="EXTRA" in environment):
                process = subprocess.run(
                    command, cwd=g.ROOT, env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=30,
                )
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(b"outer governance", process.stderr)
                self.assertNotIn(b"missing G0 freeze", process.stderr)
                self.assertFalse(os.path.lexists(g._OUTER_PYCACHE_PREFIX))

    def test_formal_outer_rejects_direct_script_and_wrong_expected_hash(self) -> None:
        variants = (
            [g._OUTER_PYTHON, "-I", "-B", g._OUTER_SCRIPT,
             "--action", "check-start"],
            g._outer_formal_command("check-start", "0" * 64),
        )
        for command in variants:
            process = subprocess.run(
                command,
                cwd=g.ROOT,
                env=dict(g._OUTER_ENVIRONMENT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            with self.subTest(command=command):
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn(b"missing G0 freeze", process.stderr)

    def test_outer_main_held_bytes_detect_comment_only_mutate_restore(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            source = Path(raw) / "governor_fixture.py"
            safe = b"VALUE = 1\n"
            comment_variant = safe + b"# comment-only injected bytes\n"
            source.write_bytes(safe)
            original = os.lstat(source)
            code = compile(safe, os.fspath(source), "exec", dont_inherit=True)
            self.assertEqual(
                code,
                compile(comment_variant, os.fspath(source), "exec", dont_inherit=True),
            )
            descriptor = os.open(
                source,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            binding = {
                "fd": descriptor,
                "source_bytes": safe,
                "stat_identity": g._outer_stat_identity(os.fstat(descriptor)),
                "sha256": hashlib.sha256(safe).hexdigest(),
                "code": code,
                "carrier_source": "-c",
            }
            try:
                with mock.patch.object(g, "_OUTER_SCRIPT", os.fspath(source)), \
                     mock.patch.object(g, "_OUTER_CARRIER_BINDING", binding), \
                     mock.patch.object(g, "_OUTER_LIVE_MAIN_CODE", code):
                    self.assertEqual(
                        g._validate_outer_carrier_binding(), binding["sha256"]
                    )
                    time.sleep(0.01)
                    source.write_bytes(comment_variant)
                    source.write_bytes(safe)
                    os.utime(
                        source,
                        ns=(original.st_atime_ns, original.st_mtime_ns),
                    )
                    with self.assertRaisesRegex(RuntimeError, "identity drifted"):
                        g._validate_outer_carrier_binding()
            finally:
                os.close(descriptor)

    def test_outer_bound_loader_never_consumes_injected_pyc(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as directory:
            source = Path(directory) / "bound_fixture.py"
            source.write_bytes(b"VALUE = 'source'\n")
            loader = g._OuterBoundSourceLoader("scripts.bound_fixture", os.fspath(source))
            try:
                with mock.patch.object(sys, "pycache_prefix", None):
                    cache = Path(importlib.util.cache_from_source(os.fspath(source)))
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"attacker-controlled-pyc")
                module = types.ModuleType("scripts.bound_fixture")
                module.__file__ = os.fspath(source)
                module.__loader__ = loader
                with mock.patch.object(
                    importlib.machinery.SourceFileLoader,
                    "get_code",
                    side_effect=AssertionError("base loader/pyc path was reached"),
                ):
                    loader.exec_module(module)
                self.assertEqual(module.VALUE, "source")
                loader.validate()
            finally:
                loader.close()

    def test_outer_bound_loader_defeats_source_mutate_load_restore(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as directory:
            source = Path(directory) / "bound_fixture.py"
            safe = b"VALUE = 'safe'\n"
            evil = b"VALUE = 'evil'\n"
            self.assertEqual(len(safe), len(evil))
            source.write_bytes(safe)
            original_stat = source.stat()
            loader = g._OuterBoundSourceLoader("scripts.bound_fixture", os.fspath(source))
            try:
                time.sleep(0.01)
                source.write_bytes(evil)
                module = types.ModuleType("scripts.bound_fixture")
                module.__file__ = os.fspath(source)
                module.__loader__ = loader
                loader.exec_module(module)
                self.assertEqual(module.VALUE, "safe")
                source.write_bytes(safe)
                os.utime(
                    source,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
                with self.assertRaisesRegex(RuntimeError, "source identity drifted"):
                    loader.validate()
            finally:
                loader.close()

    def test_static_authority_revalidates_full_outer_held_helper_closure(self) -> None:
        marker = RuntimeError("held helper closure drift")
        with mock.patch.object(g, "_OUTER_GUARD_ACTIVE", True), \
             mock.patch.object(
                 g, "_validate_outer_workspace_module_closure", side_effect=marker
             ) as closure, self.assertRaisesRegex(RuntimeError, "held helper closure drift"):
            g._static_authority_check()
        self.assertEqual(closure.call_count, 1)

    def test_formal_namespaces_are_still_absent(self) -> None:
        _inputs, _helpers, _python, _vins, authority = g._current_contract_inputs()
        paths = (
            g.FREEZE,
            *g.publication_paths(authority["job_hash"]),
            g.OUTPUT,
            g.POST,
            g.PROBE_INTENT,
            g.PROBE_FAILURE,
        )
        for path in paths:
            self.assertFalse(os.path.lexists(path), os.fspath(path))


class TypedScientificComparisonTests(unittest.TestCase):
    def summary_value(self, reference: str) -> dict[str, object]:
        arms: dict[str, object] = {}
        for name in g.ARMS:
            arms[name] = {
                "ape_max_m": 0.2, "ape_median_m": 0.08, "ape_rmse_m": 0.1,
                "audit": {"duplicate_count": 0, "finite_count": 900, "raw_count": 900,
                          "rejected_nonfinite_count": 0, "unique_count": 900},
                "bracket_gap_max_s": 0.11, "bracket_gap_p50_s": 0.1,
                "bracket_gap_p95_s": 0.105, "legacy_max_reference_reuse": 10,
                "legacy_pair_count": 900, "legacy_timestamp_error_max_s": 0.05,
                "legacy_timestamp_error_p95_s": 0.04,
                "legacy_unique_assignment_error_max_s": 0.03,
                "legacy_unique_assignment_error_p95_s": 0.02,
                "legacy_unique_assignment_pair_count": 91,
                "legacy_unique_reference_used": 91, "matched_count": 90,
                "rejection_histogram": {"INTERPOLATED": 90},
                "rpe_max_m": 0.05, "rpe_median_m": 0.02, "rpe_pairs": 89,
                "rpe_rmse_m": 0.03, "valid_grid_count": 90,
            }
        protocol = g._expected_summary_protocol()
        protocol["reference"] = reference
        return {
            "protocol": protocol,
            "support": {
                "ape_valid": True, "common_coverage": 1.0, "common_span_s": 89.0,
                "grid_count": 90, "matched_count": 90, "rpe_pairs": 89,
                "rpe_valid": True, "segment_count": 1,
                "window_duration_s": g._evaluator_window_duration_s(),
            },
            "reference": {
                "audit": {"duplicate_count": 0, "finite_count": 91, "raw_count": 91,
                          "rejected_nonfinite_count": 0, "unique_count": 91},
                "bracket_gap_max_s": 1.01, "bracket_gap_p50_s": 1.0,
                "bracket_gap_p95_s": 1.005,
                "rejection_histogram": {"INTERPOLATED": 90}, "valid_grid_count": 90,
            },
            "arms": arms,
        }

    def summary(self, reference: str) -> bytes:
        return (json.dumps(self.summary_value(reference), sort_keys=True) + "\n").encode()

    def metrics(self) -> bytes:
        summary = self.summary_value("/proc/self/fd/41:/aqualoc/colmap_gt")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=sorted({"arm", *g._TRAJECTORY_SCALAR_KEYS}))
        writer.writeheader()
        for name, arm in summary["arms"].items():
            writer.writerow({"arm": name, **{key: arm[key] for key in g._TRAJECTORY_SCALAR_KEYS}})
        return output.getvalue().encode()

    def grid(self) -> bytes:
        output = io.StringIO(newline="")
        fields = ["timestamp", "reference_valid", *(f"{name}_valid" for name in g.ARMS), "common_valid", "segment_id"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for index in range(g.EXPECTED_GRID_COUNT):
            writer.writerow({
                "timestamp": g._evaluator_grid_timestamp_text(index),
                "reference_valid": 1, **{f"{name}_valid": 1 for name in g.ARMS},
                "common_valid": 1, "segment_id": 0,
            })
        return output.getvalue().encode()

    def summary_value_with_single_hole(self, reference: str) -> dict[str, object]:
        value = self.summary_value(reference)
        value["support"].update({
            "common_coverage": 89 / 90,
            "matched_count": 89,
            "rpe_pairs": 87,
            "segment_count": 2,
        })
        invalid_arm = next(iter(g.ARMS))
        for name, arm in value["arms"].items():
            arm["matched_count"] = 89
            arm["rpe_pairs"] = 87
            if name == invalid_arm:
                arm["valid_grid_count"] = 89
                arm["rejection_histogram"] = {
                    "INTERPOLATED": 89,
                    "OUT_OF_RANGE": 1,
                }
        return value

    def grid_with_single_hole(self, *, following_segment: int) -> bytes:
        output = io.StringIO(newline="")
        fields = ["timestamp", "reference_valid", *(f"{name}_valid" for name in g.ARMS), "common_valid", "segment_id"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        invalid_arm = next(iter(g.ARMS))
        for index in range(g.EXPECTED_GRID_COUNT):
            arm_valid = {name: 1 for name in g.ARMS}
            if index == 45:
                arm_valid[invalid_arm] = 0
            common_valid = int(all(arm_valid.values()))
            segment_id = -1 if not common_valid else (0 if index < 45 else following_segment)
            writer.writerow({
                "timestamp": g._evaluator_grid_timestamp_text(index),
                "reference_valid": 1,
                **{f"{name}_valid": arm_valid[name] for name in g.ARMS},
                "common_valid": common_valid,
                "segment_id": segment_id,
            })
        return output.getvalue().encode()

    def test_only_procfd_colon_topic_reference_is_normalized(self) -> None:
        value = g._normalized_summary(
            self.summary("/proc/self/fd/41:/aqualoc/colmap_gt"), "/proc/self/fd/41"
        )
        self.assertEqual(value["protocol"]["reference"], f"{g.RAW_BAG}:{g.REFERENCE_TOPIC}")
        for invalid in (
            "/proc/self/fd/41", "/proc/self/fd/0:/aqualoc/colmap_gt",
            "/proc/self/fd/41:/wrong", f"{g.RAW_BAG}:{g.REFERENCE_TOPIC}",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(g.GovernanceError):
                g._normalized_summary(self.summary(invalid))

    def payloads(self) -> dict[str, dict[str, bytes]]:
        result: dict[str, dict[str, bytes]] = {}
        for role, fd in (("primary", 41), ("verification", 52)):
            result[role] = {
                "common_support_summary.json": self.summary(f"/proc/self/fd/{fd}:/aqualoc/colmap_gt"),
                "common_support_metrics.csv": self.metrics(),
                "common_grid_audit.csv": self.grid(),
                g.RUNTIME_RECEIPT_NAME: json.dumps({"role": role}).encode(),
            }
        return result

    def test_summary_and_both_csv_outputs_are_fully_compared(self) -> None:
        payloads = self.payloads()
        with mock.patch.object(
            g, "_validate_runtime_receipt", side_effect=lambda _b, role, _f: {"role": role}
        ), mock.patch.object(g, "_runtime_semantic_identity", return_value={"same": True}):
            summary, comparison = g._compare_roles(payloads, None, fake_freeze())
        self.assertEqual(summary["protocol"], g._expected_summary_protocol())
        self.assertTrue(comparison["metrics_csv_json_semantics_exact"])
        self.assertTrue(comparison["grid_csv_json_semantics_exact"])

    def test_any_nonreference_summary_leaf_or_csv_byte_difference_fails(self) -> None:
        for target in ("common_support_summary.json", "common_support_metrics.csv", "common_grid_audit.csv"):
            payloads = self.payloads()
            if target == "common_support_summary.json":
                altered = self.summary_value("/proc/self/fd/52:/aqualoc/colmap_gt")
                altered["arms"]["GFTTBIRTH_RAWLK"]["ape_rmse_m"] = 0.11
                payloads["verification"][target] = (json.dumps(altered, sort_keys=True) + "\n").encode()
            else:
                payloads["verification"][target] += b"DIFFERENT"
            with self.subTest(target=target), mock.patch.object(
                g, "_validate_runtime_receipt", side_effect=lambda _b, role, _f: {"role": role}
            ), mock.patch.object(g, "_runtime_semantic_identity", return_value={"same": True}), self.assertRaises(g.GovernanceError):
                g._compare_roles(payloads, None, fake_freeze())

    def test_protocol_support_and_reference_authority_are_strict(self) -> None:
        for mutation in ("protocol", "support", "reference_count"):
            value = self.summary_value("/proc/self/fd/41:/aqualoc/colmap_gt")
            if mutation == "protocol":
                value["protocol"]["contrast_name"] = "DIFFERENT"
            elif mutation == "support":
                value["support"]["ape_valid"] = False
            else:
                value["reference"]["audit"]["raw_count"] = 90
            with self.subTest(mutation=mutation), self.assertRaises(g.GovernanceError):
                g._normalized_summary((json.dumps(value, sort_keys=True) + "\n").encode(), "/proc/self/fd/41")

    def test_binary80_window_duration_and_grid_path_are_exact(self) -> None:
        expected = 89.98707520007156
        self.assertEqual(g._evaluator_window_duration_s(), expected)
        self.assertNotEqual(
            g._evaluator_window_duration_s(),
            float(g.WINDOW_END) - float(g.WINDOW_START),
        )
        self.assertEqual(g._evaluator_grid_timestamp_text(0), "1542829016.7004354")
        self.assertEqual(g._evaluator_grid_timestamp_text(89), "1542829105.7004354")
        self.assertEqual(g._evaluator_grid_span_s(0, 89), 89.0)
        for adjacent in (
            float.fromhex("0x1.67f2c3d75bfffp+6"),
            float.fromhex("0x1.67f2c3d75c001p+6"),
        ):
            value = self.summary_value("/proc/self/fd/41:/aqualoc/colmap_gt")
            value["support"]["window_duration_s"] = adjacent
            with self.subTest(adjacent=adjacent), self.assertRaises(g.GovernanceError):
                g._normalized_summary(
                    (json.dumps(value, sort_keys=True) + "\n").encode(),
                    "/proc/self/fd/41",
                )

    def test_rejection_histogram_valid_reasons_bind_valid_grid_count(self) -> None:
        for target in ("reference", next(iter(g.ARMS))):
            value = self.summary_value("/proc/self/fd/41:/aqualoc/colmap_gt")
            record = value["reference"] if target == "reference" else value["arms"][target]
            record["rejection_histogram"] = {"INTERPOLATED": 89, "OUT_OF_RANGE": 1}
            with self.subTest(target=target), self.assertRaisesRegex(
                g.GovernanceError, "valid reasons differ"
            ):
                g._normalized_summary(
                    (json.dumps(value, sort_keys=True) + "\n").encode(),
                    "/proc/self/fd/41",
                )

    def test_grid_common_span_is_exactly_bound_to_first_and_last_common_stamp(self) -> None:
        summary = g._normalized_summary(
            self.summary("/proc/self/fd/41:/aqualoc/colmap_gt"),
            "/proc/self/fd/41",
        )
        g._validate_grid_csv(summary, self.grid())
        summary["support"]["common_span_s"] = 88.0
        with self.assertRaisesRegex(g.GovernanceError, "CSV/JSON support semantics"):
            g._validate_grid_csv(summary, self.grid())

    def test_one_grid_hole_must_start_a_new_segment(self) -> None:
        value = self.summary_value_with_single_hole(
            "/proc/self/fd/41:/aqualoc/colmap_gt"
        )
        summary = g._normalized_summary(
            (json.dumps(value, sort_keys=True) + "\n").encode(),
            "/proc/self/fd/41",
        )
        g._validate_grid_csv(summary, self.grid_with_single_hole(following_segment=1))
        with self.assertRaisesRegex(g.GovernanceError, "segment identity differs"):
            g._validate_grid_csv(
                summary,
                self.grid_with_single_hole(following_segment=0),
            )

    def test_csv_json_semantic_mismatch_fails_even_when_roles_match(self) -> None:
        for target in ("common_support_metrics.csv", "common_grid_audit.csv"):
            payloads = self.payloads()
            if target == "common_support_metrics.csv":
                changed = payloads["primary"][target].replace(b",0.1,", b",0.12,", 1)
            else:
                changed = payloads["primary"][target].replace(b",1,1,1,1,0\r\n", b",1,1,1,0,-1\r\n", 1)
            self.assertNotEqual(changed, payloads["primary"][target])
            payloads["primary"][target] = changed
            payloads["verification"][target] = changed
            with self.subTest(target=target), mock.patch.object(
                g, "_validate_runtime_receipt", side_effect=lambda _b, role, _f: {"role": role}
            ), mock.patch.object(g, "_runtime_semantic_identity", return_value={"same": True}), self.assertRaises(g.GovernanceError):
                g._compare_roles(payloads, None, fake_freeze())


class ProcessReceiptTests(unittest.TestCase):
    def test_durable_launch_intent_exactly_binds_pending_single_attempt(self) -> None:
        freeze = fake_freeze()
        value = launch_intent("primary", freeze)
        g._validate_launch_intent(value, "primary", freeze)
        for mutate in ("argv", "environment", "attempt"):
            altered = copy.deepcopy(value)
            if mutate == "argv":
                altered["actual_procfd_argv"][-1] = "DIFFERENT"
            elif mutate == "environment":
                altered["actual_environment_sha256"] = "b" * 64
            else:
                altered["authorized_process_start_count"] = 2
            altered["launch_intent_hash"] = g.p07gov.canonical_json_hash(
                altered, "launch_intent_hash"
            )
            with self.subTest(mutate=mutate), self.assertRaises(g.GovernanceError):
                g._validate_launch_intent(altered, "primary", freeze)

    def test_procfd_to_canonical_mapping_and_bound_content_are_exact(self) -> None:
        freeze = fake_freeze()
        value = process_receipt("primary", freeze)
        g._validate_process_receipt(value, "primary", freeze)
        for mutate in ("argv", "binding"):
            altered = copy.deepcopy(value)
            if mutate == "argv":
                altered["actual_procfd_argv"][-1] = "DIFFERENT"
            else:
                altered["actual_procfd_binding_records"][str(g.RAW_BAG)]["record"]["sha256"] = "b" * 64
            altered["process_receipt_hash"] = g.p07gov.canonical_json_hash(
                altered, "process_receipt_hash"
            )
            with self.subTest(mutate=mutate), self.assertRaises(g.GovernanceError):
                g._validate_process_receipt(altered, "primary", freeze)

    def test_runtime_receipt_crossbinds_argv_environment_and_sealed_locators(self) -> None:
        freeze = fake_freeze()
        process = process_receipt("primary", freeze)
        mapping = process["actual_procfd_aliases"]
        environment = g._materialize_environment(
            process["authorized_environment_template"], mapping
        )
        runtime = {
            "execution": {
                "sys_argv": process["actual_procfd_argv"][3:],
                "process_argv": process["actual_procfd_argv"],
                "environment": environment,
                "target_signal_mask": child_target_signal_mask(),
            },
            "sealed_sources": {
                "python_interpreter": {"locator": mapping[str(g.PYTHON)]},
                "bootstrap": {"locator": mapping[str(g.BOOTSTRAP)]},
                "wrapper": {"locator": mapping["${EPOCH_WRAPPER_PROCFD}"]},
                "evaluator_base": {"locator": mapping["${EVALUATOR_BASE_PROCFD}"]},
                "evaluator_core": {"locator": mapping["${TRAJECTORY_CORE_PROCFD}"]},
            },
        }
        g._validate_runtime_process_binding(runtime, process, "primary")
        runtime["execution"]["environment"]["PATH"] = "/tmp"
        with self.assertRaises(g.GovernanceError):
            g._validate_runtime_process_binding(runtime, process, "primary")

    def test_popen_receipt_is_one_attempt_fixed_timeout_and_stream_digest(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")

        class Process:
            pid = 321
            returncode = 0

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.timeout = timeout
                return b"stdout", b"stderr"

        process = Process()
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )
        with mock.patch.object(g.subprocess, "Popen", return_value=process) as popen:
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(process.timeout, g.PROCESS_TIMEOUT_SECONDS)
        self.assertEqual(value["classification"], "EXITED_RC0")
        self.assertEqual(value["attempt_count"], 1)
        self.assertNotIn("stdout", json.dumps(value["stdout"]))
        self.assertEqual(value["stdout"]["size_bytes"], 6)

    def test_timeout_is_killed_and_classified_without_retry(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")

        class Process:
            pid = 654
            returncode = None
            calls = 0
            terminated = False

            def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(["fixture"], timeout)
                self.returncode = -15
                return b"partial", b"timeout"

            def kill(self) -> None:
                self.returncode = -9

            def terminate(self) -> None:
                self.terminated = True

        process = Process()
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )
        with mock.patch.object(g.subprocess, "Popen", return_value=process) as popen:
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(value["classification"], "TIMEOUT_TERMINATED")
        self.assertTrue(value["timed_out"])
        self.assertTrue(process.terminated)
        self.assertEqual(value["termination_signal"], 15)
        self.assertTrue(value["child_reaped"])

    def test_wait_baseexception_terminates_and_reaps_without_retry(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )

        class Process:
            pid = 777
            returncode = None
            calls = 0
            terminated = False

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise KeyboardInterrupt("injected wait interrupt")
                self.returncode = -15
                return b"partial-out", b"partial-err"

            def terminate(self) -> None:
                self.terminated = True

        process = Process()
        with mock.patch.object(g.subprocess, "Popen", return_value=process) as popen:
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertEqual(popen.call_count, 1)
        self.assertTrue(process.terminated)
        self.assertEqual(value["classification"], "WAIT_ERROR_TERMINATED")
        self.assertEqual(value["process_start_count"], 1)
        self.assertTrue(value["no_retry"])
        self.assertTrue(value["child_reaped"])
        self.assertIn("KeyboardInterrupt", value["wait_error"]["class"])

    def test_popen_start_error_is_terminal_evidence_without_orphan_or_retry(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )
        with mock.patch.object(
            g.subprocess, "Popen", side_effect=OSError("injected start failure")
        ) as popen:
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(value["classification"], "PROCESS_START_ERROR")
        self.assertEqual(value["process_start_count"], 0)
        self.assertIsNone(value["pid"])
        self.assertTrue(value["child_reaped"])
        self.assertIn("OSError", value["wait_error"]["class"])

    def test_evaluator_signal_after_spawn_is_caught_cleaned_and_reaped(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )

        class Process:
            pid = 8801
            returncode: int | None = None
            calls = 0
            terminated = False

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    handler = signal.getsignal(signal.SIGTERM)
                    self.assert_handler(handler)
                    handler(signal.SIGTERM, None)
                    raise AssertionError("owned signal handler did not interrupt wait")
                self.returncode = -signal.SIGTERM
                return b"", b"terminated"

            @staticmethod
            def assert_handler(handler: object) -> None:
                if not callable(handler):
                    raise AssertionError("spawn guard handler is absent")

            def terminate(self) -> None:
                self.terminated = True

        process = Process()
        with mock.patch.object(g.subprocess, "Popen", return_value=process):
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertTrue(process.terminated)
        self.assertEqual(value["classification"], "WAIT_ERROR_TERMINATED")
        self.assertEqual(value["spawn_signal_guard"]["received_signals"], ["SIGTERM"])
        self.assertTrue(value["child_reaped"])

    def test_evaluator_post_reap_pre_finish_signal_cannot_publish_rc0(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )

        class Process:
            pid = 8802
            returncode: int | None = None

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.returncode = 0
                return b"done", b""

        original = g._SpawnSignalGuard.begin_cleanup
        injected = False

        def inject_after_reap(guard: object) -> None:
            nonlocal injected
            original(guard)
            if not injected:
                injected = True
                guard._handler(signal.SIGTERM, None)

        with mock.patch.object(g.subprocess, "Popen", return_value=Process()), \
             mock.patch.object(g._SpawnSignalGuard, "begin_cleanup", inject_after_reap):
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertEqual(value["status"], "PROCESS_FAILURE_EVIDENCE")
        self.assertEqual(value["classification"], "WAIT_ERROR_TERMINATED")
        self.assertEqual(value["return_code"], 0)
        self.assertEqual(value["spawn_signal_guard"]["received_signals"], ["SIGTERM"])

    def test_evaluator_pid_capture_interrupt_reaps_returned_process(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )

        class Process:
            returncode: int | None = None
            terminated = False

            @property
            def pid(self) -> int:
                raise KeyboardInterrupt("after Popen return before PID capture")

            def terminate(self) -> None:
                self.terminated = True

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.returncode = -signal.SIGTERM
                return b"", b"reaped"

        process = Process()
        with mock.patch.object(g.subprocess, "Popen", return_value=process):
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        self.assertTrue(process.terminated)
        self.assertEqual(value["classification"], "SPAWN_WINDOW_ERROR_TERMINATED")
        self.assertFalse(
            value["spawn_signal_guard"]["pid_captured_while_handlers_installed"]
        )
        self.assertTrue(value["child_reaped"])

    def test_failed_process_receipt_is_durable_terminal_no_retry_evidence(self) -> None:
        freeze = fake_freeze()
        mapping = aliases("primary")
        environment = g._materialize_environment(
            freeze["authorized_environment_templates"]["primary"], mapping
        )
        with mock.patch.object(g.subprocess, "Popen", side_effect=OSError("boom")):
            value = g._launch_role(
                "primary",
                g._materialize_strings(g.canonical_role_argv("primary"), mapping),
                environment,
                g._procfd_numbers(mapping, label="fixture"),
                freeze,
                mapping,
                "e" * 64,
            )
        with tempfile.TemporaryDirectory() as raw:
            directory_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with ExitStack() as stack:
                    g._write_failed_process_receipt(
                        stack, directory_fd, "primary", value
                    )
                    persisted = json.loads(
                        Path(raw, "primary_failed_process_receipt.json").read_bytes()
                    )
                    self.assertEqual(persisted, value)
                    with self.assertRaises(Exception):
                        g._write_failed_process_receipt(
                            stack, directory_fd, "primary", value
                        )
            finally:
                os.close(directory_fd)

    def test_persistent_runtime_hold_closes_fds_when_enter_validation_fails(self) -> None:
        with tempfile.NamedTemporaryFile() as source:
            source.write(b"runtime")
            source.flush()
            record = g.bootstrap.persistent_file_identity(source.name)
            hold = g._HeldPersistentRuntimeFile(record, "fixture")
            with mock.patch.object(hold, "validate", side_effect=g.GovernanceError("fail")):
                with self.assertRaises(g.GovernanceError):
                    hold.__enter__()
            self.assertEqual(hold.lexical_fd, -1)
            self.assertEqual(hold.resolved_fd, -1)

    def test_persistent_runtime_hold_detects_mutate_restore_and_keeps_fd_until_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw, "runtime.so")
            path.write_bytes(b"original-runtime")
            record_value = g.bootstrap.persistent_file_identity(str(path))
            original_mtime = path.stat().st_mtime_ns
            original_mode = stat.S_IMODE(path.stat().st_mode)
            hold = g._HeldPersistentRuntimeFile(record_value, "fixture")
            with self.assertRaises(g.GovernanceError):
                with hold:
                    self.assertGreaterEqual(hold.lexical_fd, 0)
                    self.assertGreaterEqual(hold.resolved_fd, 0)
                    time.sleep(0.01)  # Cross the filesystem ctime clock tick.
                    path.write_bytes(b"changed-runtime!")
                    path.write_bytes(b"original-runtime")
                    os.chmod(path, 0o600)
                    os.chmod(path, original_mode)
                    os.utime(path, ns=(original_mtime, original_mtime))
                    hold.validate()
            self.assertEqual(hold.lexical_fd, -1)
            self.assertEqual(hold.resolved_fd, -1)


class ProbeTransactionTests(unittest.TestCase):
    def _capture(
        self, stack: ExitStack, root: Path
    ) -> tuple[g._OneRunProbeCapture, list[str], dict[str, str], tuple[int, ...]]:
        canonical = ["/usr/bin/python", "-I", "-B", "/workspace/bootstrap", "--probe"]
        actual = ["/proc/self/fd/31", "-I", "-B", "/proc/self/fd/32", "--probe"]
        environment = {"PATH": "/usr/bin", "ROLE": "runtime_probe"}
        capture = g._OneRunProbeCapture(
            stack=stack,
            canonical_argv=canonical,
            source_records={"python": record("python"), "bootstrap": record("bootstrap")},
            intent_path=root / "probe_intent.json",
            failure_path=root / "probe_failure.json",
        )
        return capture, actual, environment, (31, 32)

    def _run(
        self,
        capture: g._OneRunProbeCapture,
        actual: list[str],
        environment: dict[str, str],
        pass_fds: tuple[int, ...],
    ) -> subprocess.CompletedProcess:
        return capture.run(
            actual,
            check=False,
            cwd="/",
            env=environment,
            pass_fds=pass_fds,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=g.RUNTIME_PROBE_TIMEOUT_SECONDS,
        )

    def test_probe_normal_path_persists_intent_and_starts_exactly_once(self) -> None:
        class Process:
            pid = 4101
            returncode = 0

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.timeout = timeout
                return b"runtime-json", b""

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            with mock.patch.object(g.subprocess, "Popen", return_value=Process()) as popen:
                completed = self._run(capture, actual, environment, pass_fds)
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(completed.returncode, 0)
            self.assertTrue((root / "probe_intent.json").is_file())
            self.assertFalse(os.path.lexists(root / "probe_failure.json"))
            intent = json.loads((root / "probe_intent.json").read_bytes())
            g._validate_probe_launch_intent(
                intent,
                canonical_argv=capture.canonical_argv,
                source_records=capture.source_records,
                intent_path=root / "probe_intent.json",
                failure_path=root / "probe_failure.json",
            )

    def test_probe_intent_same_bytes_different_inode_is_rejected_before_popen(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            original = g._write_all

            def swap_after_write(descriptor: int, content: bytes) -> None:
                original(descriptor, content)
                path = root / "probe_intent.json"
                os.rename(path, root / "probe_intent.old")
                path.write_bytes(content)

            with mock.patch.object(g, "_write_all", side_effect=swap_after_write), \
                 mock.patch.object(
                     g.subprocess, "Popen", side_effect=AssertionError("Popen reached")
                 ) as popen, self.assertRaisesRegex(
                     Exception, "retained canonical leaf drifted"
                 ):
                self._run(capture, actual, environment, pass_fds)
            self.assertEqual(popen.call_count, 0)

    def test_probe_failure_same_bytes_different_inode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            original = g._write_all
            writes = 0

            def swap_failure_after_write(descriptor: int, content: bytes) -> None:
                nonlocal writes
                original(descriptor, content)
                writes += 1
                if writes == 2:
                    path = root / "probe_failure.json"
                    os.rename(path, root / "probe_failure.old")
                    path.write_bytes(content)

            with mock.patch.object(g, "_write_all", side_effect=swap_failure_after_write), \
                 mock.patch.object(g.subprocess, "Popen", side_effect=OSError("start")) as popen, \
                 self.assertRaisesRegex(Exception, "retained canonical leaf drifted"):
                self._run(capture, actual, environment, pass_fds)
            self.assertEqual(popen.call_count, 1)

    def test_probe_start_error_is_durable_and_second_attempt_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            with mock.patch.object(g.subprocess, "Popen", side_effect=OSError("start")) as popen:
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            self.assertEqual(popen.call_count, 1)
            intent = json.loads((root / "probe_intent.json").read_bytes())
            failure = json.loads((root / "probe_failure.json").read_bytes())
            g._validate_probe_failure_receipt(failure, intent)
            self.assertEqual(failure["classification"], "PROCESS_START_ERROR")
            self.assertTrue(failure["child_reaped"])
            with ExitStack() as retry_stack:
                retry, argv, env, fds = self._capture(retry_stack, root)
                with mock.patch.object(
                    g.subprocess, "Popen", side_effect=AssertionError("retry launched")
                ) as retry_popen:
                    with self.assertRaisesRegex(g.GovernanceError, "no retry"):
                        self._run(retry, argv, env, fds)
                self.assertEqual(retry_popen.call_count, 0)

    def test_probe_keyboard_interrupt_terms_and_reaps_with_failure_evidence(self) -> None:
        class Process:
            pid = 4102
            returncode: int | None = None
            calls = 0
            terminated = False

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise KeyboardInterrupt("wait interrupt")
                self.returncode = -signal.SIGTERM
                return b"partial", b"interrupt"

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            process = Process()
            with mock.patch.object(g.subprocess, "Popen", return_value=process):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertTrue(process.terminated)
            self.assertEqual(failure["classification"], "WAIT_ERROR_TERMINATED")
            self.assertTrue(failure["child_reaped"])
            self.assertIn("KeyboardInterrupt", failure["wait_error"]["class"])

    def test_probe_pid_capture_interrupt_reaps_returned_process(self) -> None:
        class Process:
            returncode: int | None = None
            terminated = False

            @property
            def pid(self) -> int:
                raise KeyboardInterrupt("after Popen return before probe PID capture")

            def terminate(self) -> None:
                self.terminated = True

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.returncode = -signal.SIGTERM
                return b"", b"reaped"

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            process = Process()
            with mock.patch.object(g.subprocess, "Popen", return_value=process):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertTrue(process.terminated)
            self.assertEqual(
                failure["classification"], "SPAWN_WINDOW_ERROR_TERMINATED"
            )
            self.assertFalse(
                failure["spawn_signal_guard"][
                    "pid_captured_while_handlers_installed"
                ]
            )
            self.assertTrue(failure["child_reaped"])

    def test_probe_post_reap_pre_finish_signal_is_terminal_failure(self) -> None:
        class Process:
            pid = 4107
            returncode: int | None = None

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.returncode = 0
                return b"runtime-json", b""

        original = g._SpawnSignalGuard.begin_cleanup
        injected = False

        def inject_after_reap(guard: object) -> None:
            nonlocal injected
            original(guard)
            if not injected:
                injected = True
                guard._handler(signal.SIGTERM, None)

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            with mock.patch.object(g.subprocess, "Popen", return_value=Process()), \
                 mock.patch.object(g._SpawnSignalGuard, "begin_cleanup", inject_after_reap):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertEqual(failure["classification"], "WAIT_ERROR_TERMINATED")
            self.assertEqual(failure["return_code"], 0)
            self.assertEqual(
                failure["spawn_signal_guard"]["received_signals"], ["SIGTERM"]
            )

    def test_probe_timeout_is_terminal_reaped_evidence(self) -> None:
        class Process:
            pid = 4103
            returncode: int | None = None
            calls = 0
            terminated = False

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(["probe"], timeout)
                self.returncode = -signal.SIGTERM
                return b"partial", b"timeout"

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            process = Process()
            with mock.patch.object(g.subprocess, "Popen", return_value=process):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertTrue(process.terminated)
            self.assertTrue(failure["timed_out"])
            self.assertEqual(failure["classification"], "TIMEOUT_TERMINATED")
            self.assertTrue(failure["child_reaped"])

    def test_probe_term_failure_escalates_to_kill_and_reaps(self) -> None:
        class Process:
            pid = 4104
            returncode: int | None = None
            calls = 0
            killed = False

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise KeyboardInterrupt("wait interrupt")
                if self.calls == 2:
                    raise subprocess.TimeoutExpired(["probe"], timeout)
                self.returncode = -signal.SIGKILL
                return b"partial", b"killed"

            def terminate(self) -> None:
                raise OSError("TERM failed")

            def kill(self) -> None:
                self.killed = True
                self.returncode = -signal.SIGKILL

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            process = Process()
            with mock.patch.object(g.subprocess, "Popen", return_value=process), \
                 mock.patch.object(g.os, "kill", side_effect=OSError("signal failed")):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertTrue(process.killed)
            self.assertTrue(failure["child_reaped"])
            self.assertEqual(failure["return_code"], -signal.SIGKILL)
            self.assertGreaterEqual(len(failure["cleanup_errors"]), 3)

    def test_probe_nonzero_rc_is_terminal_no_retry_evidence(self) -> None:
        class Process:
            pid = 4105
            returncode = 17

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                return b"", b"probe failed"

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            capture, actual, environment, pass_fds = self._capture(stack, root)
            with mock.patch.object(g.subprocess, "Popen", return_value=Process()):
                with self.assertRaises(g.GovernanceError):
                    self._run(capture, actual, environment, pass_fds)
            failure = json.loads((root / "probe_failure.json").read_bytes())
            self.assertEqual(failure["classification"], "EXITED_NONZERO")
            self.assertEqual(failure["return_code"], 17)
            self.assertTrue(failure["no_retry"])

    def test_probe_post_wait_receipt_validation_error_is_terminal_evidence(self) -> None:
        class Process:
            pid = 4106
            returncode = 0

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                return b"malformed-runtime-receipt", b""

        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw, ExitStack() as stack:
            root = Path(raw)
            intent_path = root / "probe_intent.json"
            failure_path = root / "probe_failure.json"

            def capture_then_reject(**_kwargs: object) -> object:
                facade = g.bootstrap.subprocess
                facade.run(
                    [
                        "/proc/self/fd/31", "-I", "-B", "/proc/self/fd/32",
                        g.bootstrap.PROBE_ARGUMENT, "/proc/self/fd/33", g.REFERENCE_TOPIC,
                    ],
                    check=False,
                    cwd="/",
                    env={"PATH": "/usr/bin", "ROLE": "runtime_probe"},
                    pass_fds=(31, 32, 33),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=g.RUNTIME_PROBE_TIMEOUT_SECONDS,
                )
                raise ValueError("invalid runtime receipt")

            with mock.patch.object(g, "PROBE_INTENT", intent_path), \
                 mock.patch.object(g, "PROBE_FAILURE", failure_path), \
                 mock.patch.object(g.subprocess, "Popen", return_value=Process()), \
                 mock.patch.object(
                     g.bootstrap, "capture_freeze_runtime", side_effect=capture_then_reject
                 ), self.assertRaisesRegex(ValueError, "invalid runtime receipt"):
                g._capture_runtime_closure(stack)
            intent = json.loads(intent_path.read_bytes())
            failure = json.loads(failure_path.read_bytes())
            g._validate_probe_failure_receipt(failure, intent)
            self.assertEqual(
                failure["classification"], "POST_WAIT_RECEIPT_VALIDATION_ERROR"
            )
            self.assertEqual(failure["return_code"], 0)
            self.assertTrue(failure["child_reaped"])


class GovernanceFlowTests(unittest.TestCase):
    def test_retained_created_directories_reject_post_acquisition_swap(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            top = root / "top"
            with self.assertRaisesRegex(Exception, "retained directory drifted"):
                with g._create_retained_workspace_directory(
                    root, top, label="fixture top"
                ) as (_top_fd, validate_top):
                    os.rename(top, root / "top.old")
                    top.mkdir(mode=0o700)
                    validate_top()

            parent = root / "parent"
            parent.mkdir(mode=0o700)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaisesRegex(Exception, "retained directory drifted"):
                    with g._create_retained_child_directory(
                        parent_fd, "role", label="fixture role"
                    ) as (_role_fd, validate_role):
                        os.rename(parent / "role", parent / "role.old")
                        (parent / "role").mkdir(mode=0o700)
                        validate_role()
            finally:
                os.close(parent_fd)

    def test_three_governed_json_leaves_remain_same_inodes_until_exit(self) -> None:
        for name in ("primary_launch.json", "verification_launch.json", "bound.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                dir=g.ROOT
            ) as raw:
                root = Path(raw)
                parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    value = {"leaf": name}
                    with self.assertRaisesRegex(
                        Exception, "retained canonical leaf drifted"
                    ):
                        with g._write_held_canonical_json_at(
                            parent_fd, name, value, label=name
                        ) as (validator, _record):
                            os.rename(root / name, root / f"{name}.old")
                            (root / name).write_bytes(g._render_canonical_json(value))
                            validator()
                finally:
                    os.close(parent_fd)

    def test_existing_output_and_closeout_holds_reject_same_bytes_new_inode(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            output = root / "summary.json"
            output.write_bytes(b"payload")
            parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaisesRegex(
                    Exception, "retained canonical leaf drifted"
                ):
                    with g._hold_existing_leaf_at(
                        parent_fd, output.name, label="held output"
                    ) as (_content, validator):
                        os.rename(output, root / "summary.old")
                        output.write_bytes(b"payload")
                        validator()
            finally:
                os.close(parent_fd)

            closeout = root / "closeout.json"
            value = {"closeout": True}
            closeout.write_bytes(g._render_canonical_json(value))
            with self.assertRaisesRegex(
                Exception, "retained canonical leaf drifted"
            ):
                with g._hold_existing_canonical_json_rooted(
                    root, closeout, value, label="held closeout"
                ) as validator:
                    os.rename(closeout, root / "closeout.old")
                    closeout.write_bytes(g._render_canonical_json(value))
                    validator()

    def test_run_barrier_revalidates_outer_closure_before_first_popen(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            staging = root / "staging"
            intent = {
                "staging_absolute": str(staging),
                "closeout_path_absolute": str(root / "closeout.json"),
            }
            freeze = {
                "input_records": {key: {} for key in g.INPUTS},
                "vins_external_runtime": {},
                "expected_runtime_closure": {"runtime_receipt": {}},
            }

            class Lease:
                def verify_unchanged(self) -> None:
                    pass

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_load_exact_intent", return_value=intent), \
                 mock.patch.object(g, "_retained_workspace_record_validators", return_value=[]), \
                 mock.patch.object(g, "_retained_external_record_validators", return_value=[]), \
                 mock.patch.object(g, "_retained_runtime_file_holds", return_value=[]), \
                 mock.patch.object(
                     g, "_sealed_execution_inputs",
                     return_value=({"reference_bag": "/proc/self/fd/1"}, [], Lease()),
                 ), mock.patch.object(
                     g, "_actual_role_contract", return_value=([], {}, {})
                 ), mock.patch.object(
                     g, "_launch_intent",
                     return_value={"launch_intent_hash": "a" * 64},
                 ), mock.patch.object(
                     g, "_validate_outer_workspace_module_closure",
                     side_effect=RuntimeError("held helper closure drift"),
                 ) as closure, mock.patch.object(
                     g, "_launch_role", side_effect=AssertionError("Popen reached")
                 ) as launch, self.assertRaisesRegex(
                     RuntimeError, "held helper closure drift"
                 ):
                g._run_evaluation_with_held_intent(
                    freeze, intent, lambda: None, lambda: None
                )
            self.assertEqual(closure.call_count, 1)
            self.assertEqual(launch.call_count, 0)

    def test_closeout_must_rebuild_exactly_from_held_receipt_and_seal_bytes(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            destination = root / "result"
            intent = g.publisher.build_publication_intent(
                root=root,
                job_id="fixture",
                job_hash="a" * 64,
                plan_hash="b" * 64,
                evaluation_lock_hash="c" * 64,
                backend_execution_lock_hash="d" * 64,
                g0_execution_authority_hash="e" * 64,
                evaluation_disposition="EVALUATE_NUMERIC",
                output_dir=destination,
            )
            receipt = {"result_receipt_hash": "f" * 64}
            seals = {
                g.publisher.MANIFEST_NAME: b"manifest\n",
                g.publisher.RECEIPT_NAME: b"receipt\n",
            }
            expected = g.publisher._build_closeout_from_retained_snapshot(
                intent, receipt, seals, root=root
            )
            with mock.patch.object(g, "ROOT", root), mock.patch.object(
                g, "OUTPUT", destination
            ):
                self.assertEqual(
                    g._validate_closeout_against_held_seals(
                        expected, intent, receipt, seals
                    ),
                    expected,
                )
                for mutation in (
                    "result_hash", "receipt_record", "manifest_record",
                    "typed_manifest_size",
                ):
                    altered = copy.deepcopy(expected)
                    if mutation == "result_hash":
                        altered["result_receipt_hash"] = "0" * 64
                    elif mutation == "receipt_record":
                        altered["receipt"]["sha256"] = "0" * 64
                    elif mutation == "manifest_record":
                        altered["output_manifest"]["size_bytes"] += 1
                    else:
                        altered["output_manifest"]["size_bytes"] = float(
                            altered["output_manifest"]["size_bytes"]
                        )
                    altered["publication_closeout_hash"] = g.p07gov.canonical_json_hash(
                        altered, "publication_closeout_hash"
                    )
                    with self.subTest(mutation=mutation), self.assertRaises(
                        g.GovernanceError
                    ):
                        g._validate_closeout_against_held_seals(
                            altered, intent, receipt, seals
                        )

    def test_run_rejects_validate_then_hold_freeze_swap_before_any_popen(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            freeze_path = root / "freeze.json"
            freeze_a = {"publication_authority": {"job_hash": "a" * 64}}
            freeze_b = {"publication_authority": {"job_hash": "b" * 64}}
            freeze_path.write_bytes(
                (json.dumps(freeze_b, indent=2, sort_keys=True) + "\n").encode()
            )
            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "FREEZE", freeze_path), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze_a), \
                 mock.patch.object(g.subprocess, "Popen", side_effect=AssertionError("Popen reached")) as popen, \
                 self.assertRaisesRegex(Exception, "initial validated object"):
                g._run_evaluation_scoped()
            self.assertEqual(popen.call_count, 0)

    def test_run_holds_created_intent_before_staging_or_popen(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            freeze_path = root / "freeze.json"
            freeze = {"authority": "A"}
            freeze_path.write_bytes(
                (json.dumps(freeze, indent=2, sort_keys=True) + "\n").encode()
            )
            intent_a = {
                "staging_absolute": str(root / "staging"),
                "intent_path_absolute": str(root / "intent.json"),
                "closeout_path_absolute": str(root / "closeout.json"),
                "publication_intent_hash": "a" * 64,
            }
            intent_b = dict(intent_a)
            intent_b["publication_intent_hash"] = "b" * 64

            original_write = g._write_all

            def swap_after_write(descriptor: int, content: bytes) -> None:
                original_write(descriptor, content)
                intent_path = Path(intent_a["intent_path_absolute"])
                os.rename(intent_path, intent_path.with_suffix(".old"))
                intent_path.write_bytes(
                    (json.dumps(intent_b, indent=2, sort_keys=True) + "\n").encode()
                )

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "FREEZE", freeze_path), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_build_intent", return_value=intent_a), \
                 mock.patch.object(g, "_write_all", side_effect=swap_after_write), \
                 mock.patch.object(g.subprocess, "Popen", side_effect=AssertionError("Popen reached")) as popen, \
                 self.assertRaisesRegex(Exception, "retained canonical leaf drifted"):
                g._run_evaluation_scoped()
            self.assertFalse((root / "staging").exists())
            self.assertEqual(popen.call_count, 0)

    def test_role_directory_swap_is_rejected_before_seal_or_publish(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            staging = root / "staging"
            staging.mkdir()
            role = staging / "primary"
            role.mkdir()
            descriptor = os.open(role, os.O_RDONLY | os.O_DIRECTORY)
            old = staging / "old"
            os.rename(role, old)
            role.mkdir()
            try:
                with mock.patch.object(
                    g.publisher, "seal_staging_result_retained",
                    side_effect=AssertionError("seal reached"),
                ) as seal, self.assertRaises(Exception):
                    g.publisher.assert_retained_workspace_directory(
                        root, role, descriptor, label="swapped role fixture"
                    )
                self.assertEqual(seal.call_count, 0)
            finally:
                os.close(descriptor)

    def test_real_p07_retained_staging_seal_rename_and_closeout(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            destination = root / "result"
            digest = "a" * 64
            intent = g.publisher.build_publication_intent(
                root=root,
                job_id="fixture",
                job_hash=digest,
                plan_hash="b" * 64,
                evaluation_lock_hash="c" * 64,
                backend_execution_lock_hash="d" * 64,
                g0_execution_authority_hash="e" * 64,
                evaluation_disposition="EVALUATE_NUMERIC",
                output_dir=destination,
            )
            staging = Path(intent["staging_absolute"])
            intent_path = Path(intent["intent_path_absolute"])
            closeout_path = Path(intent["closeout_path_absolute"])
            g.publisher.create_publication_intent(intent_path, intent, root=root)
            rc = -1
            with g._create_retained_workspace_directory(
                root,
                staging,
                label="fixture run staging",
                relocated_to=destination,
            ) as (staging_fd, staging_validator):
                held_identity = os.fstat(staging_fd)
                g.publisher.write_json_exclusive_retained_directory(
                    staging_fd, g.publisher.BOUND_SUMMARY_NAME,
                    {"fixture": True}, label="fixture payload",
                )
                g.publisher.seal_staging_result_retained(
                    intent, root=root, staging_fd=staging_fd
                )
                closeout = g.publisher.publish_staging(
                    intent, root=root, closeout_path=closeout_path,
                    staging_fd=staging_fd,
                )
                staging_validator(destination)
                g.publisher.validate_closeout(closeout, intent=intent, root=root)
                rc = 0
            receipt, records = g.publisher.validate_sealed_result(
                destination, intent=intent, root=root
            )
            g.publisher.validate_closeout(closeout, intent=intent, root=root)
            self.assertEqual(receipt["payload_records"], records)
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.lexists(staging))
            self.assertTrue(destination.is_dir())
            published_identity = destination.stat()
            self.assertEqual(
                (published_identity.st_dev, published_identity.st_ino),
                (held_identity.st_dev, held_identity.st_ino),
            )
            self.assertTrue(closeout_path.is_file())
            closeout_path.write_bytes(b'{"duplicate":1,"duplicate":1}\n')
            with mock.patch.object(g, "ROOT", root), mock.patch.object(
                g, "OUTPUT", destination
            ), self.assertRaisesRegex(Exception, "duplicate JSON key"):
                with g._held_published_result(intent):
                    self.fail("duplicate-key closeout was accepted")

    def test_real_transactional_json_rolls_back_only_own_inode(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            guard = root / "guard.txt"
            guard.write_bytes(b"guard")
            record_value = {
                "path": "guard.txt",
                "sha256": hashlib.sha256(b"guard").hexdigest(),
                "size_bytes": 5,
            }
            destination = root / "post.json"
            calls = 0

            def reject_after_link() -> None:
                nonlocal calls
                calls += 1
                if calls >= 3:
                    raise g.GovernanceError("injected post-link validation failure")

            with self.assertRaises(g.GovernanceError):
                g.publisher.publish_json_transactional_rooted(
                    root,
                    destination,
                    {"post": True},
                    guard_records=[record_value],
                    validate=reject_after_link,
                )
            self.assertFalse(os.path.lexists(destination))
            self.assertEqual(guard.read_bytes(), b"guard")
            self.assertFalse(any(".partial." in item.name for item in root.iterdir()))

    def test_real_transactional_post_retain_hook_holds_single_link_to_return(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            holds = ExitStack()
            guard = root / "guard.txt"
            guard.write_bytes(b"guard")
            guard_record = {
                "path": "guard.txt",
                "sha256": hashlib.sha256(b"guard").hexdigest(),
                "size_bytes": 5,
            }
            post_path = root / "post.json"
            post = {"pass": True, "post_hash": "a" * 64}
            retained: list[object] = []

            def retain(
                parent_fd: int,
                name: str,
                staged_fd: int,
                content: bytes,
            ) -> None:
                staged = os.fstat(staged_fd)
                linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                self.assertEqual(staged.st_nlink, 1)
                self.assertEqual(linked.st_nlink, 1)
                self.assertEqual(
                    (staged.st_dev, staged.st_ino),
                    (linked.st_dev, linked.st_ino),
                )
                self.assertEqual(content, g._render_canonical_json(post))
                validator = holds.enter_context(
                    g._hold_existing_canonical_json_rooted(
                        root,
                        post_path,
                        post,
                        label="real retained post",
                        expected_identity=staged,
                    )
                )
                validator()
                retained.append(validator)

            g.publisher.publish_json_transactional_rooted(
                root,
                post_path,
                post,
                guard_records=[guard_record],
                validate=lambda: None,
                retain_linked=retain,
            )
            self.assertEqual(len(retained), 1)
            retained[0]()
            os.rename(post_path, root / "post.old")
            post_path.write_bytes(g._render_canonical_json(post))
            with self.assertRaisesRegex(Exception, "retained canonical leaf drifted"):
                retained[0]()
            with self.assertRaisesRegex(Exception, "retained canonical leaf drifted"):
                holds.close()

    def test_retain_hook_failure_rolls_back_own_post_but_preserves_race_winner(self) -> None:
        for replacement in (False, True):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory(
                dir=g.ROOT
            ) as raw:
                root = Path(raw)
                guard = root / "guard.txt"
                guard.write_bytes(b"guard")
                guard_record = {
                    "path": "guard.txt",
                    "sha256": hashlib.sha256(b"guard").hexdigest(),
                    "size_bytes": 5,
                }
                post_path = root / "post.json"

                def reject(
                    _parent_fd: int,
                    _name: str,
                    _staged_fd: int,
                    _content: bytes,
                ) -> None:
                    if replacement:
                        os.rename(post_path, root / "owned.old")
                        post_path.write_bytes(b"independent winner\n")
                    raise g.GovernanceError("retain hook rejected")

                with self.assertRaisesRegex(g.GovernanceError, "retain hook rejected"):
                    g.publisher.publish_json_transactional_rooted(
                        root,
                        post_path,
                        {"post": True},
                        guard_records=[guard_record],
                        validate=lambda: None,
                        retain_linked=reject,
                    )
                if replacement:
                    self.assertEqual(post_path.read_bytes(), b"independent winner\n")
                else:
                    self.assertFalse(os.path.lexists(post_path))

    def test_real_seal_post_transaction_retains_single_link_until_return(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            freeze_path = root / "freeze.json"
            corrected = root / "corrected.json"
            intent_path = root / "intent.json"
            closeout_path = root / "closeout.json"
            post_path = root / "post.json"
            for path in (freeze_path, corrected, intent_path, closeout_path):
                path.write_bytes(b'{}\n')
            freeze = {"freeze_hash": "f" * 64}
            intent = {
                "intent_path_absolute": str(intent_path),
                "closeout_path_absolute": str(closeout_path),
            }
            closeout = {"publication_closeout_hash": "c" * 64}
            post = {"pass": True, "post_hash": "0" * 64}
            post["post_hash"] = g._self_hash(post, "post_hash")
            lease_events: list[str] = []

            @contextmanager
            def held(_intent: object):
                yield closeout, {"result_receipt_hash": "r" * 64}, [], {}, {}, lambda: None

            original_hold = g._hold_existing_canonical_json_rooted

            @contextmanager
            def record_post_hold(*args: object, **kwargs: object):
                identity = kwargs.get("expected_identity")
                self.assertIsNotNone(identity)
                self.assertEqual(identity.st_nlink, 1)
                lease_events.append("enter")
                with original_hold(*args, **kwargs) as validator:
                    yield validator
                lease_events.append("exit")

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "FREEZE", freeze_path), \
                 mock.patch.object(g, "CORRECTED_SEAL", corrected), \
                 mock.patch.object(g, "POST", post_path), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_load_exact_intent", return_value=intent), \
                 mock.patch.object(g, "_held_published_result", held), \
                 mock.patch.object(g, "_validate_closeout_against_held_seals", return_value=closeout), \
                 mock.patch.object(g, "_build_post_from_held", return_value=post), \
                 mock.patch.object(
                     g,
                     "_hold_existing_canonical_json_rooted",
                     record_post_hold,
                 ):
                rc = g._seal_post_with_held_authorities(
                    freeze, intent, lambda: None, lambda: None
                )
                self.assertEqual(lease_events, ["enter", "exit"])
            self.assertEqual(rc, 0)
            self.assertEqual(post_path.read_bytes(), g._render_canonical_json(post))
            self.assertEqual(post_path.stat().st_nlink, 1)

    def test_reserved_namespace_race_aborts_transaction_and_rolls_back_own_inode(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            guard = root / "guard.txt"
            guard.write_bytes(b"guard")
            guard_record = {
                "path": "guard.txt",
                "sha256": hashlib.sha256(b"guard").hexdigest(),
                "size_bytes": 5,
            }
            reserved = {
                key: str(root / key)
                for key in (
                    "destination", "staging", "intent", "closeout", "post",
                    "probe_intent", "probe_failure",
                )
            }
            Path(reserved["probe_intent"]).write_bytes(b"retained-probe-intent")
            payload = {"reserved_paths": reserved}
            destination = root / "freeze.json"
            calls = 0

            def validate() -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    Path(reserved["post"]).write_bytes(b"race")
                with mock.patch.object(
                    g, "PROBE_INTENT", Path(reserved["probe_intent"])
                ):
                    g._assert_reserved_outputs_absent(payload)

            with self.assertRaises(g.GovernanceError):
                g.publisher.publish_json_transactional_rooted(
                    root, destination, {"freeze": True},
                    guard_records=[guard_record], validate=validate,
                )
            self.assertFalse(os.path.lexists(destination))
            self.assertEqual(Path(reserved["post"]).read_bytes(), b"race")

    def test_publication_boundary_is_truthful_nested_and_restored(self) -> None:
        self.assertIs(g.publisher.gov, g.p07gov)
        self.assertEqual(g.p07gov.OUTCOME_BOUNDARY, g.P07_NATIVE_OUTCOME_BOUNDARY)
        with g._post_result_publication_semantics():
            self.assertEqual(g.p07gov.OUTCOME_BOUNDARY, g.PUBLICATION_TECHNICAL_BOUNDARY)
            with g._post_result_publication_semantics():
                self.assertEqual(g.p07gov.OUTCOME_BOUNDARY, g.PUBLICATION_TECHNICAL_BOUNDARY)
        self.assertEqual(g.p07gov.OUTCOME_BOUNDARY, g.P07_NATIVE_OUTCOME_BOUNDARY)
        self.assertEqual(g._PUBLICATION_SCOPE_DEPTH, 0)
        self.assertIsNone(g._PUBLICATION_SCOPE_OWNER)

    def test_publication_boundary_rejects_unknown_entry_state(self) -> None:
        previous = g.p07gov.OUTCOME_BOUNDARY
        g.p07gov.OUTCOME_BOUNDARY = "UNKNOWN"
        try:
            with self.assertRaises(g.GovernanceError):
                with g._post_result_publication_semantics():
                    pass
        finally:
            g.p07gov.OUTCOME_BOUNDARY = previous

    def test_publication_boundary_rejects_other_thread_and_restores_after_mutation(self) -> None:
        errors: list[type[BaseException]] = []
        with g._post_result_publication_semantics():
            def enter_from_other_thread() -> None:
                try:
                    with g._post_result_publication_semantics():
                        pass
                except BaseException as error:
                    errors.append(type(error))

            thread = threading.Thread(target=enter_from_other_thread)
            thread.start()
            thread.join()
        self.assertEqual(errors, [g.GovernanceError])
        with self.assertRaises(g.GovernanceError):
            with g._post_result_publication_semantics():
                g.p07gov.OUTCOME_BOUNDARY = "MUTATED"
        self.assertEqual(g.p07gov.OUTCOME_BOUNDARY, g.P07_NATIVE_OUTCOME_BOUNDARY)
        self.assertEqual(g._PUBLICATION_SCOPE_DEPTH, 0)
        self.assertIsNone(g._PUBLICATION_SCOPE_OWNER)

    def test_post_commit_validator_uses_live_held_snapshot_and_no_process(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            freeze = {"freeze_hash": "f" * 64}
            intent = {
                "intent_path_absolute": str(root / "intent.json"),
                "closeout_path_absolute": str(root / "closeout.json"),
            }
            closeout = {"publication_closeout_hash": "c" * 64}
            post = {"pass": True, "post_hash": "p" * 64}
            live_calls: list[int] = []
            exit_events: list[str] = []

            def live() -> None:
                live_calls.append(1)

            @contextmanager
            def held(_intent: object):
                live()
                yield closeout, {"result_receipt_hash": "r" * 64}, [], {}, {}, live
                live()
                exit_events.append("output_exit")

            @contextmanager
            def held_authority(*_args: object, **_kwargs: object):
                yield live
                exit_events.append("authority_exit")

            original_post_hold = g._hold_existing_canonical_json_rooted

            @contextmanager
            def held_post(*args: object, **kwargs: object):
                with original_post_hold(*args, **kwargs) as validator:
                    yield validator
                exit_events.append("post_exit")

            def publish(
                _root: Path,
                path: Path,
                payload: object,
                *,
                guard_records: object,
                validate: object,
                retain_linked: object,
            ) -> dict[str, object]:
                validate()
                path.write_bytes(g._render_canonical_json(payload))
                parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                staged_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    retain_linked(
                        parent_fd, path.name, staged_fd,
                        g._render_canonical_json(payload),
                    )
                finally:
                    os.close(staged_fd)
                    os.close(parent_fd)
                validate()
                return {"published": True}

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "POST", root / "post.json"), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_load_exact_intent", return_value=intent), \
                 mock.patch.object(g, "_held_exact_json_authority", held_authority), \
                 mock.patch.object(g, "_held_published_result", held), \
                 mock.patch.object(g, "_hold_existing_canonical_json_rooted", held_post), \
                 mock.patch.object(g, "_validate_closeout_against_held_seals", return_value=closeout), \
                 mock.patch.object(g, "_build_post_from_held", return_value=post), \
                 mock.patch.object(g, "_workspace_record", return_value=record("fixture")), \
                 mock.patch.object(g.publisher, "publish_json_transactional_rooted", side_effect=publish), \
                 mock.patch.object(g.p07gov, "validate_self_hash", return_value="p" * 64), \
                 mock.patch.object(g.subprocess, "Popen", side_effect=AssertionError("POST launched process")), \
                 mock.patch.object(g.subprocess, "run", side_effect=AssertionError("POST launched process")):
                self.assertEqual(g._seal_post_scoped(), 0)
            self.assertGreaterEqual(len(live_calls), 7)
            self.assertEqual(exit_events[-1], "post_exit")
            self.assertEqual(exit_events.count("authority_exit"), 2)
            self.assertLess(exit_events.index("output_exit"), exit_events.index("post_exit"))
            self.assertLess(
                max(
                    index for index, value in enumerate(exit_events)
                    if value == "authority_exit"
                ),
                exit_events.index("post_exit"),
            )

    def test_check_post_rejects_duplicate_keys_and_typed_bool_int_alias(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            post_path = root / "post.json"
            freeze = {"freeze_hash": "f" * 64}
            intent = {"intent_path_absolute": str(root / "intent.json")}

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "POST", post_path), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_load_exact_intent", return_value=intent):
                post_path.write_bytes(
                    b'{"pass":true,"pass":true,"post_hash":"' + b"a" * 64 + b'"}\n'
                )
                with self.assertRaisesRegex(Exception, "duplicate JSON key"):
                    g._check_post_with_held_authorities(
                        freeze, intent, lambda: None, lambda: None
                    )

                observed = {"pass": 1, "post_hash": "a" * 64}
                expected = {"pass": True, "post_hash": "a" * 64}
                post_path.write_bytes(g._render_canonical_json(observed))

                @contextmanager
                def held(_intent: object):
                    yield {}, {}, [], {}, {}, lambda: None

                with mock.patch.object(
                    g.p07gov, "validate_self_hash", return_value="a" * 64
                ), mock.patch.object(
                    g, "_held_published_result", held
                ), mock.patch.object(
                    g, "_build_post_from_held", return_value=expected
                ), self.assertRaisesRegex(
                    g.GovernanceError, "differs from held published snapshot"
                ):
                    g._check_post_with_held_authorities(
                        freeze, intent, lambda: None, lambda: None
                    )

    def test_seal_post_holds_linked_post_inode_through_final_validators(self) -> None:
        with tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
            root = Path(raw)
            post_path = root / "post.json"
            freeze = {"freeze_hash": "f" * 64}
            intent = {
                "intent_path_absolute": str(root / "intent.json"),
                "closeout_path_absolute": str(root / "closeout.json"),
            }
            closeout = {"publication_closeout_hash": "c" * 64}
            post = {"pass": True, "post_hash": "a" * 64}

            @contextmanager
            def held(_intent: object):
                yield closeout, {"result_receipt_hash": "r" * 64}, [], {}, {}, lambda: None

            def publish(
                _root: Path,
                path: Path,
                payload: object,
                *,
                guard_records: object,
                validate: object,
                retain_linked: object,
            ) -> dict[str, object]:
                validate()
                content = g._render_canonical_json(payload)
                path.write_bytes(content)
                parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                staged_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    retain_linked(parent_fd, path.name, staged_fd, content)
                finally:
                    os.close(staged_fd)
                    os.close(parent_fd)
                validate()
                os.rename(path, root / "post.old")
                path.write_bytes(content)
                validate()  # Same bytes on a new inode must fail.
                return {"published": True}

            with mock.patch.object(g, "ROOT", root), \
                 mock.patch.object(g, "POST", post_path), \
                 mock.patch.object(g, "validate_freeze_static", return_value=freeze), \
                 mock.patch.object(g, "_load_exact_intent", return_value=intent), \
                 mock.patch.object(g, "_held_published_result", held), \
                 mock.patch.object(g, "_validate_closeout_against_held_seals", return_value=closeout), \
                 mock.patch.object(g, "_build_post_from_held", return_value=post), \
                 mock.patch.object(g, "_workspace_record", return_value=record("fixture")), \
                 mock.patch.object(
                     g.publisher,
                     "publish_json_transactional_rooted",
                     side_effect=publish,
                 ), self.assertRaisesRegex(
                     Exception, "retained canonical leaf drifted"
                 ):
                g._seal_post_with_held_authorities(
                    freeze, intent, lambda: None, lambda: None
                )

    def test_seal_and_check_hold_freeze_and_intent_before_post_work(self) -> None:
        def write_canonical(path: Path, value: object) -> None:
            path.write_bytes(
                (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
            )

        for action in (g._seal_post_scoped, g._check_post_scoped):
            for swapped in ("freeze", "intent"):
                with self.subTest(action=action.__name__, swapped=swapped), \
                     tempfile.TemporaryDirectory(dir=g.ROOT) as raw:
                    root = Path(raw)
                    freeze_path = root / "freeze.json"
                    post_path = root / "post.json"
                    freeze_a = {"authority": "A"}
                    freeze_b = {"authority": "B"}
                    intent_path = root / "intent.json"
                    intent_a = {
                        "intent_path_absolute": str(intent_path),
                        "publication_intent_hash": "a" * 64,
                    }
                    intent_b = dict(intent_a)
                    intent_b["publication_intent_hash"] = "b" * 64
                    write_canonical(
                        freeze_path, freeze_b if swapped == "freeze" else freeze_a
                    )
                    write_canonical(
                        intent_path, intent_b if swapped == "intent" else intent_a
                    )
                    with mock.patch.object(g, "ROOT", root), \
                         mock.patch.object(g, "FREEZE", freeze_path), \
                         mock.patch.object(g, "POST", post_path), \
                         mock.patch.object(g, "validate_freeze_static", return_value=freeze_a), \
                         mock.patch.object(g, "_load_exact_intent", return_value=intent_a), \
                         mock.patch.object(
                             g.publisher, "publish_json_transactional_rooted",
                             side_effect=AssertionError("POST publish reached"),
                         ) as publish, self.assertRaisesRegex(
                             Exception, "differ from initial validated object"
                         ):
                        action()
                    self.assertEqual(publish.call_count, 0)
                    self.assertFalse(os.path.lexists(post_path))

    def test_only_freeze_capture_and_evaluation_run_have_process_launch_sites(self) -> None:
        capture_source = inspect.getsource(g._OneRunProbeCapture.run)
        run_source = inspect.getsource(g._launch_role)
        post_source = "\n".join(
            inspect.getsource(function)
            for function in (
                g.validate_freeze_static,
                g._seal_post_scoped,
                g.seal_post,
                g._check_post_scoped,
                g.check_post,
                g._build_post_from_held,
            )
        )
        spawn_source = inspect.getsource(g._SpawnSignalGuard.spawn)
        self.assertIn("subprocess.Popen", spawn_source)
        self.assertNotIn("subprocess.Popen", capture_source)
        self.assertNotIn("= subprocess.Popen(", run_source)
        self.assertNotIn("subprocess.", post_source)
        self.assertNotIn("_capture_runtime_closure", post_source)

    def test_write_freeze_holds_python_and_revalidates_reserved_namespaces(self) -> None:
        source = inspect.getsource(g.write_freeze)
        self.assertIn("backend.SealedFileLease", source)
        self.assertGreaterEqual(source.count("lease.verify_unchanged()"), 3)
        self.assertGreaterEqual(source.count("_assert_reserved_outputs_absent"), 2)
        self.assertIn("freeze_transaction_validator", source)


if __name__ == "__main__":
    unittest.main()
