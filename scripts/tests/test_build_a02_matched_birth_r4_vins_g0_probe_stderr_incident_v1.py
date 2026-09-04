#!/usr/bin/env python3
"""Adversarial tests for the additive A02 r4 G0 stderr incident builder."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import build_a02_matched_birth_r4_vins_g0_probe_stderr_incident_v1 as incident


SHA_A = "a" * 64
SHA_B = "b" * 64


class RecordTests(unittest.TestCase):
    @staticmethod
    def contract(sha256: str, size_bytes: int, job_hash: str = SHA_B) -> dict[str, object]:
        staging, intent_path, closeout = incident._v2_publication_paths(job_hash)
        return {
            "schema_version": "aqua-fe-matched-birth-r4-vins-g0-v2-incident-namespace-contract-v1",
            "successor_governor": {"path": "scripts/govern_matched_birth_r4_vins_g0_v2.py",
                                     "sha256": sha256, "size_bytes": size_bytes},
            "job_id": "matched_birth_r4_vins_g0_v2", "job_hash": job_hash,
            "destination": str(incident.V2_RESULT), "staging": str(staging),
            "intent": str(intent_path), "closeout": str(closeout),
            "freeze": str(incident.V2_FREEZE), "post": str(incident.V2_POST),
            "probe_intent": str(incident.V2_INTENT), "probe_failure": str(incident.V2_FAILURE),
            "probe_success": str(incident.V2_SUCCESS),
        }

    def record(self, **overrides: object) -> dict[str, object]:
        values = {"successor_sha256": SHA_A, "successor_size_bytes": 123,
                  "v2_job_hash": SHA_B,
                  "builder_identity": {"path": str(Path(incident.__file__).absolute()),
                                       "size_bytes": 1, "sha256": "d" * 64}}
        values.update(overrides)
        with mock.patch.object(
            incident, "_successor_contract",
            return_value=self.contract(str(values["successor_sha256"]),
                                       int(values["successor_size_bytes"]),
                                       str(values["v2_job_hash"])),
        ):
            return incident.build_record(**values)

    def test_schema_status_and_claim_boundary_are_narrow(self) -> None:
        value = self.record()
        self.assertEqual(value["schema_version"], incident.SCHEMA)
        self.assertFalse(value["claim_boundary"]["scientific_outcome_claimed"])
        self.assertFalse(value["claim_boundary"]["v1_stdout_or_stderr_content_claimed"])
        self.assertFalse(value["outcome_firewall"]["vio_metric_files_read"])

    def test_old_intent_exact_filesystem_identity_is_recorded(self) -> None:
        value = self.record()
        self.assertEqual(value["retained_v1_evidence"]["runtime_probe_launch_intent"],
                         incident.EXPECTED_OLD_INTENT)
        self.assertEqual(incident.EXPECTED_OLD_INTENT["mode_octal"], "0644")

    def test_unrecoverable_streams_and_missing_failure_are_truthful(self) -> None:
        old = self.record()["retained_v1_evidence"]
        self.assertTrue(old["failure_receipt_missing"])
        self.assertFalse(old["stdout_bytes_recoverable"])
        self.assertFalse(old["stderr_bytes_recoverable"])

    def test_future_v2_stderr_allowlist_is_exact(self) -> None:
        allowed = self.record()["successor_authorization"]["stderr_allowlist_for_future_v2_probe"]
        self.assertEqual(allowed, [
            {"size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(),
             "meaning": "EMPTY_STDERR"},
            {"size_bytes": 88, "sha256": incident.ROS_LZ4_WARNING_SHA256,
             "meaning": "EXACT_PREREGISTERED_ROSLZ4_WARNING_ONLY"},
        ])

    def test_only_exact_v2_namespace_is_authorized(self) -> None:
        auth = self.record()["successor_authorization"]
        self.assertEqual(auth["sole_governor"]["path"], str(incident.SUCCESSOR))
        self.assertEqual(set(auth["exact_namespace"]), {
            "incident", "freeze", "probe_intent", "probe_failure", "probe_success", "result",
            "post", "staging", "publication_intent", "publication_closeout",
        })
        self.assertFalse(auth["old_v1_namespace_retry_or_mutation_authorized"])
        self.assertFalse(auth["detector_or_feature_export_rerun_authorized"])
        self.assertFalse(auth["vins_rerun_authorized"])
        self.assertEqual(auth["authorized_successor_evaluation_namespace_count"], 1)
        self.assertEqual(auth["authorized_action_sequence"], [
            "write-freeze", "check-start", "run", "seal-post", "check-post",
        ])
        self.assertTrue(
            auth["visible_intent_without_exact_success_closeout_consumes_namespace_and_forbids_retry_or_continuation"])
        self.assertTrue(auth["success_closeout_required_before_later_actions"])
        self.assertTrue(
            auth["failure_receipt_is_best_effort_additive_not_retry_authority"])
        self.assertEqual(auth["terminal_evidence_boundary"], {
            "coverage":
                "FAIL_CLOSED_BY_VISIBLE_INTENT_WITHOUT_EXACT_SUCCESS_CLOSEOUT;RECEIPT_ONLY_WHEN_PARENT_OBSERVES_AND_COMMIT_SUCCEEDS",
            "unobservable_or_uncommittable_exclusions": [
                "SIGKILL", "SIGSTOP", "PROCESS_CRASH", "POWER_LOSS",
                "KERNEL_FAILURE", "STORAGE_FAILURE", "SIGNAL_API_FAILURE",
                "FAILURE_RECEIPT_WRITE_OR_FSYNC_FAILURE",
            ],
            "failure_receipt_io_failure_fallback":
                "VISIBLE_INTENT_ALONE_CONSUMES_NAMESPACE_NO_RETRY",
            "failure_receipt_durability_unconditional_claimed": False,
        })

    def test_builder_command_records_exact_cwd_environment_and_arguments(self) -> None:
        command = self.record()["builder_execution_contract"]
        self.assertEqual(command["working_directory"], str(incident.ROOT))
        self.assertEqual(command["environment"], incident.FROZEN_ENVIRONMENT)
        self.assertEqual(command["authorized_write_once_argv"][-1], SHA_B)
        self.assertEqual(command["scientific_evaluator_detector_vins_process_start_count"], 0)
        self.assertTrue(command["builder_process_is_publication_control_plane_only"])
        self.assertTrue(command["active_same_uid_namespace_adversary_out_of_scope"])
        self.assertEqual(
            command["commit_linearization"],
            "O_TMPFILE_HIDDEN_LINK_FSYNC_RENAMEAT2_NOREPLACE",
        )

    def test_self_hash_is_exact(self) -> None:
        value = self.record()
        self.assertEqual(value["incident_hash"], incident._self_hash(value))

    def test_malformed_successor_or_job_hash_is_rejected(self) -> None:
        with self.assertRaises(incident.IncidentError):
            self.record(successor_sha256="bad")
        with self.assertRaises(incident.IncidentError):
            self.record(successor_size_bytes=0)
        with self.assertRaises(incident.IncidentError):
            self.record(v2_job_hash="bad")

    def test_cli_job_hash_must_match_successor_pure_contract(self) -> None:
        with mock.patch.object(
            incident, "_successor_contract",
            return_value=self.contract(SHA_A, 123, "c" * 64),
        ):
            with self.assertRaisesRegex(incident.IncidentError, "CLI v2 job hash"):
                incident.build_record(successor_sha256=SHA_A,
                                      successor_size_bytes=123, v2_job_hash=SHA_B,
                                      builder_identity={"path": str(Path(incident.__file__).absolute()),
                                                        "size_bytes": 1, "sha256": "d" * 64})

    def test_outcome_firewall_rejects_nested_metric_keys(self) -> None:
        with self.assertRaisesRegex(incident.IncidentError, "outcome firewall"):
            incident._assert_firewall({"safe": [{"ape": 1}]})

    def test_frozen_v1_source_mechanically_has_late_stderr_gap(self) -> None:
        source = incident.AUTHORITIES["v1_governor"][0].read_bytes()
        incident._validate_v1_static_control_flow(source)
        mutated = source.replace(b"runtime probe emitted stderr",
                                 b"runtime probe stream differed")
        with self.assertRaisesRegex(incident.IncidentError, "control flow"):
            incident._validate_v1_static_control_flow(mutated)

    def test_live_v2_pure_contract_is_derived_from_held_source(self) -> None:
        source = incident.SUCCESSOR.read_bytes()
        sha = hashlib.sha256(source).hexdigest()
        value = incident._successor_contract(sha256=sha, size_bytes=len(source))
        self.assertEqual(set(value), incident.SUCCESSOR_CONTRACT_KEYS)
        self.assertEqual(value["successor_governor"]["sha256"], sha)
        self.assertFalse(incident.OUTPUT.exists())

    def test_held_helper_mutation_is_rejected(self) -> None:
        source = incident.SUCCESSOR.read_bytes()
        sha = hashlib.sha256(source).hexdigest()
        roles = {"child_bootstrap", "backend", "backend_evaluation", "formal_io",
                 "p07_governance", "retained_publisher", "runner"}
        helpers = {
            role: {"data": incident.AUTHORITIES[role][0].read_bytes(),
                   "validate": (lambda: None)} for role in roles
        }
        helpers["formal_io"]["validate"] = mock.Mock(
            side_effect=incident.IncidentError("synthetic helper mutation"))
        with incident._hold_directory_chain(incident.ROOT / "scripts") as scripts_hold:
            with self.assertRaisesRegex(incident.IncidentError, "helper mutation"):
                incident._evaluate_successor_contract(
                    source, sha256=sha, size_bytes=len(source), helper_sources=helpers,
                    scripts_hold=scripts_hold)

    def test_build_reads_only_its_own_source(self) -> None:
        original = Path.read_bytes
        seen: list[Path] = []
        def guarded(path: Path) -> bytes:
            seen.append(path.absolute())
            if "vio.csv" in str(path):
                raise AssertionError("VIO metric bytes were read")
            return original(path)
        with mock.patch.object(Path, "read_bytes", guarded), mock.patch.object(
            incident, "_successor_contract", return_value=self.contract(SHA_A, 123)
        ):
            incident.build_record(successor_sha256=SHA_A,
                                  successor_size_bytes=123, v2_job_hash=SHA_B,
                                  builder_identity={"path": str(Path(incident.__file__).absolute()),
                                                    "size_bytes": 1, "sha256": "d" * 64})
        self.assertEqual(seen, [])

    def test_successor_eval_restores_scripts_modules_meta_path_and_sys_path(self) -> None:
        before_path = list(sys.path)
        before_meta = list(sys.meta_path)
        before_modules = dict(sys.modules)
        before_cache = dict(sys.path_importer_cache)
        before_pycache_prefix = sys.pycache_prefix
        before_dont_write_bytecode = sys.dont_write_bytecode
        source = incident.SUCCESSOR.read_bytes()
        sha = hashlib.sha256(source).hexdigest()
        incident._successor_contract(sha256=sha, size_bytes=len(source))
        self.assertEqual(sys.path, before_path)
        self.assertEqual(sys.meta_path, before_meta)
        self.assertEqual(set(sys.modules), set(before_modules))
        for name, value in before_modules.items():
            self.assertIs(sys.modules[name], value)
        self.assertEqual(set(sys.path_importer_cache), set(before_cache))
        for name, value in before_cache.items():
            self.assertIs(sys.path_importer_cache[name], value)
        self.assertEqual(sys.pycache_prefix, before_pycache_prefix)
        self.assertEqual(sys.dont_write_bytecode, before_dont_write_bytecode)

    def test_successor_eval_rejects_unheld_workspace_import_and_restores_state(self) -> None:
        source = incident.SUCCESSOR.read_bytes()
        marker = b"from __future__ import annotations\n"
        self.assertIn(marker, source)
        attacked = source.replace(
            marker, marker + b"import scripts.unheld_workspace_attack\n", 1)
        sha = hashlib.sha256(attacked).hexdigest()
        roles = {"child_bootstrap", "backend", "backend_evaluation", "formal_io",
                 "p07_governance", "retained_publisher", "runner"}
        helpers = {
            role: {"data": incident.AUTHORITIES[role][0].read_bytes(),
                   "validate": (lambda: None)} for role in roles
        }
        before_modules = dict(sys.modules)
        before_path = list(sys.path)
        before_meta = list(sys.meta_path)
        with incident._hold_directory_chain(incident.ROOT / "scripts") as scripts_hold:
            with self.assertRaisesRegex(ImportError, "unbound workspace import denied"):
                incident._evaluate_successor_contract(
                    attacked, sha256=sha, size_bytes=len(attacked),
                    helper_sources=helpers, scripts_hold=scripts_hold)
        self.assertEqual(sys.path, before_path)
        self.assertEqual(sys.meta_path, before_meta)
        self.assertEqual(set(sys.modules), set(before_modules))
        for name, value in before_modules.items():
            self.assertIs(sys.modules[name], value)


class HoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=incident.ROOT / "papers")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_file(self, name: str = "held", data: bytes = b"evidence\n",
                  mode: int = 0o644) -> tuple[Path, dict[str, object]]:
        path = self.root / name
        path.write_bytes(data)
        os.chmod(path, mode)
        info = os.stat(path)
        return path, incident._file_record(path, data, info)

    def test_file_hold_rejects_visible_replacement(self) -> None:
        path, record = self.make_file()
        with self.assertRaisesRegex(incident.IncidentError, "drifted"):
            with incident._hold_file(path, expected=record, label="synthetic") as held:
                replacement = self.root / "replacement"
                replacement.write_bytes(b"evidence\n")
                os.chmod(replacement, 0o644)
                os.replace(replacement, path)
                held["validate"]()

    def test_file_hold_rejects_wrong_mode(self) -> None:
        path, record = self.make_file()
        record["mode_octal"] = "0444"
        with self.assertRaisesRegex(incident.IncidentError, "mode_octal"):
            with incident._hold_file(path, expected=record, label="synthetic"):
                pass

    def test_absence_hold_detects_new_entry(self) -> None:
        path = self.root / "reserved"
        with self.assertRaisesRegex(incident.IncidentError, "present"):
            with incident._hold_absences([path]) as held:
                path.write_bytes(b"x")
                held["validate"]()

    def test_absence_hold_detects_ancestor_rename(self) -> None:
        ancestor = self.root / "ancestor"
        parent = ancestor / "parent"
        parent.mkdir(parents=True)
        path = parent / "reserved"
        moved = self.root / "moved"
        with self.assertRaisesRegex(incident.IncidentError, "reachable"):
            with incident._hold_absences([path]) as held:
                os.rename(ancestor, moved)
                held["validate"]()

    def test_publication_sibling_scan_uses_held_dirfd(self) -> None:
        allowed = [self.root / "one.staging"]
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        observed: list[object] = []
        original = os.scandir
        def scan(value: object):
            observed.append(value)
            return original(value)
        try:
            with mock.patch.object(os, "scandir", side_effect=scan):
                incident._assert_publication_sibling_namespace_exact(
                    basename="synthetic", allowed=allowed,
                    label="synthetic", parent_fd=fd)
        finally:
            os.close(fd)
        self.assertEqual(observed, [fd])


class MainAndLiveBoundaryTests(unittest.TestCase):
    def test_live_machine_incident_remains_absent(self) -> None:
        self.assertFalse(incident.OUTPUT.exists())

    def test_check_action_never_publishes(self) -> None:
        record = {"incident_hash": SHA_A}
        @contextmanager
        def guard(*args: object, **kwargs: object):
            yield {"validate": lambda: None, "absence_hold": {"parents": {}}}
        with mock.patch.object(incident, "build_record", return_value=record), \
             mock.patch.object(incident, "publication_guard", guard):
            rc = incident.main([
                "--action", "check", "--successor-governor-sha256", SHA_A,
                "--successor-governor-size-bytes", "123", "--v2-job-hash", SHA_B,
            ])
        self.assertEqual(rc, 0)
        self.assertIsNone(incident._AQUAFE_INCIDENT_FINAL_COMMIT)

    def test_write_once_rejects_in_process_argv_substitution(self) -> None:
        rc = incident.main([
            "--action", "write-once", "--successor-governor-sha256", SHA_A,
            "--successor-governor-size-bytes", "123", "--v2-job-hash", SHA_B,
        ])
        self.assertEqual(rc, 2)
        self.assertFalse(incident.OUTPUT.exists())

    def test_direct_script_write_once_is_rejected_without_machine_json(self) -> None:
        command = [
            "/usr/bin/python3.8", "-I", "-B", str(Path(incident.__file__).absolute()),
            "--action", "write-once", "--successor-governor-sha256", SHA_A,
            "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B,
        ]
        result = subprocess.run(
            command, cwd=str(incident.ROOT), env=dict(incident.FROZEN_ENVIRONMENT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"carrier binding is absent", result.stderr)
        self.assertFalse(incident.OUTPUT.exists())

    def test_carrier_binding_crossbinds_held_source_and_live_code(self) -> None:
        path = Path(incident.__file__).absolute()
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            data = os.pread(fd, info.st_size, 0)
            binding = {
                "fd": fd, "source_bytes": data,
                "stat_identity": incident._stat_token(info),
                "sha256": hashlib.sha256(data).hexdigest(),
                "code": incident._LIVE_MAIN_CODE, "carrier_source": "-c",
            }
            with mock.patch.object(incident, "_CARRIER_BINDING", binding):
                observed = incident._carrier_builder_identity()
                self.assertEqual(observed["sha256"], binding["sha256"])
                binding["code"] = compile(b"pass", "<wrong>", "exec")
                with self.assertRaisesRegex(incident.IncidentError, "carrier source"):
                    incident._carrier_builder_identity()
        finally:
            os.close(fd)

    def test_main_prepares_commit_only_after_guard_final(self) -> None:
        events: list[str] = []
        @contextmanager
        def guard(*args: object, **kwargs: object):
            value = {
                "validate": lambda: events.append("guard_validate"),
                "absence_hold": {"parents": {}},
                "required_records": [{
                    "path": str(Path(incident.__file__).absolute()),
                    "size_bytes": 1, "sha256": SHA_A,
                    "device_id": 1, "inode": 2, "uid": 1000,
                    "mode_octal": "0644", "nlink": 1,
                }],
                "required_absent": [
                    str(incident.OUTPUT), str(incident.PENDING_OUTPUT),
                ],
                "required_sibling_namespaces": [],
            }
            yield value
            events.append("guard_final")
        argv = [str(Path(incident.__file__).absolute()), "--action", "write-once",
                "--successor-governor-sha256", SHA_A,
                "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(incident, "_validate_write_execution",
                               return_value={"path": str(Path(incident.__file__).absolute()),
                                             "size_bytes": 1, "sha256": "d" * 64}), \
             mock.patch.object(incident, "build_record", return_value={"incident_hash": SHA_A}), \
             mock.patch.object(incident, "publication_guard", guard):
            rc = incident.main()
        self.assertEqual(rc, 0)
        self.assertEqual(events[-1], "guard_final")
        self.assertIsNotNone(incident._AQUAFE_INCIDENT_FINAL_COMMIT)

    def test_late_guard_finalizer_failure_never_prepares_or_writes_adoption(self) -> None:
        @contextmanager
        def guard(*args: object, **kwargs: object):
            yield {
                "validate": lambda: None,
                "absence_hold": {"parents": {}},
                "required_records": [],
                "required_absent": [
                    str(incident.OUTPUT), str(incident.PENDING_OUTPUT),
                ],
                "required_sibling_namespaces": [],
            }
            raise incident.IncidentError("late held-source finalizer")

        argv = [str(Path(incident.__file__).absolute()), "--action", "write-once",
                "--successor-governor-sha256", SHA_A,
                "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B]
        with tempfile.TemporaryDirectory(dir=incident.ROOT / "papers") as raw, \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(incident, "OUTPUT", Path(raw) / "incident.json"), \
             mock.patch.object(incident, "_validate_write_execution",
                               return_value={"path": str(Path(incident.__file__).absolute()),
                                             "size_bytes": 1, "sha256": "d" * 64}), \
             mock.patch.object(incident, "build_record", return_value={"incident_hash": SHA_A}), \
             mock.patch.object(incident, "publication_guard", guard):
            rc = incident.main()
            self.assertEqual(rc, 2)
            self.assertIsNone(incident._AQUAFE_INCIDENT_FINAL_COMMIT)
            self.assertFalse(incident.OUTPUT.exists())

    def test_carrier_commits_only_after_clean_inner_completion(self) -> None:
        with tempfile.TemporaryDirectory(dir=incident.ROOT / "papers") as raw:
            root = Path(raw)
            authority = root / "authority.txt"
            authority.write_bytes(b"authority\n")
            info = authority.stat()
            record = {
                "path": str(authority), "size_bytes": info.st_size,
                "sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
                "device_id": info.st_dev, "inode": info.st_ino,
                "uid": info.st_uid, "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
                "nlink": info.st_nlink,
            }
            output = root / "incident.json"
            pending = output.with_name(f".{output.name}.pending_v1")
            sibling_parent = root / "siblings"
            sibling_parent.mkdir()
            old_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r1"
            new_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r2"
            old_prefix = f".{old_basename}.c51e1b38696ca936"
            new_prefix = f".{new_basename}.{SHA_B[:16]}"
            sibling_contracts = [
                {
                    "parent": str(sibling_parent), "basename": old_basename,
                    "allowed_names": sorted([
                        old_prefix + ".staging",
                        old_prefix + ".publication_intent_v1.json",
                        old_prefix + ".publication_closeout_v1.json",
                    ]),
                },
                {
                    "parent": str(sibling_parent), "basename": new_basename,
                    "allowed_names": sorted([
                        new_prefix + ".staging",
                        new_prefix + ".publication_intent_v1.json",
                        new_prefix + ".publication_closeout_v1.json",
                    ]),
                },
            ]
            content = b'{"status":"ADOPTED"}\n'
            commit = {
                "path": str(output), "pending_path": str(pending),
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(), "mode": 0o444,
                "required_records": [record],
                "required_absent": [str(output), str(pending)],
                "required_sibling_namespaces": sibling_contracts,
            }
            fixture = root / "fixture.py"
            fixture.write_text(
                "_AQUAFE_INCIDENT_FINAL_COMMIT = " + repr(commit)
                + "\n_AQUAFE_INCIDENT_CLEAN_SUCCESS = "
                + repr({"action": "write-once", "exit_code": 0}) + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            command = [
                "/usr/bin/python3.8", "-I", "-B", "-c", incident._CARRIER_SOURCE,
                str(fixture), digest, "--action", "write-once",
                "--successor-governor-sha256", SHA_A,
                "--successor-governor-size-bytes", "1",
                "--v2-job-hash", SHA_B,
            ]
            process = subprocess.run(
                command, cwd=incident.ROOT, env=dict(incident.FROZEN_ENVIRONMENT),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(output.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
            self.assertFalse(pending.exists())

    def test_carrier_caught_systemexit_zero_never_commits(self) -> None:
        with tempfile.TemporaryDirectory(dir=incident.ROOT / "papers") as raw:
            root = Path(raw)
            output = root / "incident.json"
            fixture = root / "fixture.py"
            fixture.write_text(
                "_AQUAFE_INCIDENT_FINAL_COMMIT = {'path': " + repr(str(output))
                + "}\nraise SystemExit(0)\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            process = subprocess.run(
                ["/usr/bin/python3.8", "-I", "-B", "-c", incident._CARRIER_SOURCE,
                 str(fixture), digest, "--action", "write-once",
                 "--successor-governor-sha256", SHA_A,
                 "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B],
                cwd=incident.ROOT, env=dict(incident.FROZEN_ENVIRONMENT),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse(output.exists())

    def test_carrier_rejects_unexpected_publication_sibling_at_commit_edge(self) -> None:
        with tempfile.TemporaryDirectory(dir=incident.ROOT / "papers") as raw:
            root = Path(raw)
            authority = root / "authority.txt"
            authority.write_bytes(b"authority\n")
            info = authority.stat()
            authority_record = {
                "path": str(authority), "size_bytes": info.st_size,
                "sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
                "device_id": info.st_dev, "inode": info.st_ino,
                "uid": info.st_uid,
                "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
                "nlink": info.st_nlink,
            }
            output = root / "incident.json"
            pending = output.with_name(f".{output.name}.pending_v1")
            siblings = root / "siblings"
            siblings.mkdir()
            old_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r1"
            new_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r2"
            old_prefix = f".{old_basename}.c51e1b38696ca936"
            new_prefix = f".{new_basename}.{SHA_B[:16]}"
            contracts = [
                {"parent": str(siblings), "basename": old_basename,
                 "allowed_names": sorted([
                     old_prefix + ".staging",
                     old_prefix + ".publication_intent_v1.json",
                     old_prefix + ".publication_closeout_v1.json",
                 ])},
                {"parent": str(siblings), "basename": new_basename,
                 "allowed_names": sorted([
                     new_prefix + ".staging",
                     new_prefix + ".publication_intent_v1.json",
                     new_prefix + ".publication_closeout_v1.json",
                 ])},
            ]
            unexpected = siblings / f".{new_basename}.foreign.publication_intent_v1.json"
            unexpected.write_bytes(b"foreign\n")
            content = b'{"status":"ADOPTED"}\n'
            commit = {
                "path": str(output), "pending_path": str(pending),
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(), "mode": 0o444,
                "required_records": [authority_record],
                "required_absent": [str(output), str(pending)],
                "required_sibling_namespaces": contracts,
            }
            fixture = root / "fixture.py"
            fixture.write_text(
                "_AQUAFE_INCIDENT_FINAL_COMMIT = " + repr(commit)
                + "\n_AQUAFE_INCIDENT_CLEAN_SUCCESS = "
                + repr({"action": "write-once", "exit_code": 0}) + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            process = subprocess.run(
                ["/usr/bin/python3.8", "-I", "-B", "-c", incident._CARRIER_SOURCE,
                 str(fixture), digest, "--action", "write-once",
                 "--successor-governor-sha256", SHA_A,
                 "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B],
                cwd=incident.ROOT, env=dict(incident.FROZEN_ENVIRONMENT),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(pending.exists())

    def test_carrier_final_rescan_rejects_sibling_injected_after_hidden_dir_fsync(self) -> None:
        with tempfile.TemporaryDirectory(dir=incident.ROOT / "papers") as raw:
            root = Path(raw)
            authority = root / "authority.txt"
            authority.write_bytes(b"authority\n")
            info = authority.stat()
            authority_record = {
                "path": str(authority), "size_bytes": info.st_size,
                "sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
                "device_id": info.st_dev, "inode": info.st_ino,
                "uid": info.st_uid,
                "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
                "nlink": info.st_nlink,
            }
            output = root / "incident.json"
            pending = output.with_name(f".{output.name}.pending_v1")
            siblings = root / "siblings"
            siblings.mkdir()
            suffixes = (
                ".staging", ".publication_intent_v1.json",
                ".publication_closeout_v1.json",
            )
            old_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r1"
            new_basename = "formal900_r4_xfeatbirth_vs_gfttbirth_r2"
            contracts = [
                {
                    "parent": str(siblings), "basename": basename,
                    "allowed_names": sorted(
                        f".{basename}.{prefix}{suffix}" for suffix in suffixes
                    ),
                }
                for basename, prefix in (
                    (old_basename, "c51e1b38696ca936"),
                    (new_basename, SHA_B[:16]),
                )
            ]
            unexpected = (
                siblings
                / f".{new_basename}.foreign.publication_intent_v1.json"
            )
            content = b'{"status":"ADOPTED"}\n'
            commit = {
                "path": str(output), "pending_path": str(pending),
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(), "mode": 0o444,
                "required_records": [authority_record],
                "required_absent": [str(output), str(pending)],
                "required_sibling_namespaces": contracts,
            }
            fixture = root / "fixture.py"
            fixture.write_text(
                "import os\n"
                "_original_fsync = os.fsync\n"
                "_fsync_count = 0\n"
                "def _injected_fsync(fd):\n"
                " global _fsync_count\n"
                " result = _original_fsync(fd)\n"
                " _fsync_count += 1\n"
                " if _fsync_count == 3:\n"
                f"  with open({str(unexpected)!r}, 'wb') as _stream:\n"
                "   _stream.write(b'late foreign\\n')\n"
                " return result\n"
                "os.fsync = _injected_fsync\n"
                "_AQUAFE_INCIDENT_FINAL_COMMIT = " + repr(commit)
                + "\n_AQUAFE_INCIDENT_CLEAN_SUCCESS = "
                + repr({"action": "write-once", "exit_code": 0}) + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            process = subprocess.run(
                ["/usr/bin/python3.8", "-I", "-B", "-c", incident._CARRIER_SOURCE,
                 str(fixture), digest, "--action", "write-once",
                 "--successor-governor-sha256", SHA_A,
                 "--successor-governor-size-bytes", "1", "--v2-job-hash", SHA_B],
                cwd=incident.ROOT, env=dict(incident.FROZEN_ENVIRONMENT),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(b"unexpected publication sibling", process.stderr)
            self.assertFalse(output.exists())
            self.assertTrue(pending.exists())
            self.assertEqual(pending.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(pending.stat().st_mode), 0o444)


if __name__ == "__main__":
    unittest.main()
