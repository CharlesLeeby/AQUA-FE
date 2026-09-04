#!/usr/bin/env python3
"""Pure-contract and real outer-carrier tests for the alias incident builder."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path("/home/ma/AQUA-FE_WS")
SOURCE = ROOT / "scripts/build_a02_matched_birth_r4_vins_g0_runtime_alias_incident_v1.py"
SPEC = importlib.util.spec_from_file_location("runtime_alias_incident_builder", SOURCE)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _mutate_scalar(value: object) -> object:
    if value is None:
        return "MUTATED"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "_MUTATED"
    raise AssertionError(type(value))


def _scalar_paths(value: object, prefix: tuple[object, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _scalar_paths(child, prefix + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _scalar_paths(child, prefix + (index,))
    else:
        yield prefix


def _replace_path(value: object, path: tuple[object, ...]) -> None:
    parent = value
    for part in path[:-1]:
        parent = parent[part]  # type: ignore[index]
    leaf = path[-1]
    parent[leaf] = _mutate_scalar(parent[leaf])  # type: ignore[index]


def _authority_record(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    info = path.lstat()
    return {
        "path": str(path), "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "device_id": int(info.st_dev), "inode": int(info.st_ino),
        "uid": int(info.st_uid),
        "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
        "nlink": int(info.st_nlink),
    }


class _CarrierSandbox:
    """A disposable fake inner builder executed by the production carrier."""

    def __init__(self, parent: Path, content: bytes) -> None:
        self.root = parent.resolve()
        self.output = self.root / "incident.json"
        self.pending = self.root / ".incident.json.pending_v1"
        self.extra_absent = self.root / "must-stay-absent.json"
        self.content = content
        self.job_hash = "b" * 64
        self.delay = self.root / "delay.bin"
        self.delay.write_bytes(b"D" * (2 * 1024 * 1024))
        self.delay.chmod(0o444)
        self.volatile = self.root / "volatile"
        self.volatile.mkdir()
        self.target = self.volatile / "held.bin"
        self.target.write_bytes(b"held-authority\n")
        self.target.chmod(0o444)
        # Repeated reads of one held inode deliberately widen the post-link
        # validation window without changing carrier code or using a hook.
        self.records = ([_authority_record(self.delay)] * 48
                        + [_authority_record(self.target)])
        self.siblings = []
        for index, (basename, hash_prefix) in enumerate((
            ("formal900_r4_xfeatbirth_vs_gfttbirth_r1", "c51e1b38696ca936"),
            ("formal900_r4_xfeatbirth_vs_gfttbirth_r2", "48f29b21b4e9d314"),
            ("formal900_r4_xfeatbirth_vs_gfttbirth_r3", self.job_hash[:16]),
        )):
            sibling_parent = self.root / f"siblings-{index}"
            sibling_parent.mkdir()
            prefix = f".{basename}.{hash_prefix}"
            self.siblings.append({
                "parent": str(sibling_parent), "basename": basename,
                "allowed_names": sorted([
                    f"{prefix}.staging",
                    f"{prefix}.publication_intent_v1.json",
                    f"{prefix}.publication_closeout_v1.json",
                ]),
            })
        self.commit = {
            "path": str(self.output), "pending_path": str(self.pending),
            "content": content, "sha256": hashlib.sha256(content).hexdigest(),
            "mode": 0o444, "required_records": self.records,
            "required_absent": [
                str(self.output), str(self.pending), str(self.extra_absent),
            ],
            "required_sibling_namespaces": self.siblings,
        }

    def write_fake_builder(self, behavior: str = "commit") -> Path:
        source = self.root / "fake_builder.py"
        if behavior == "commit":
            code = (
                f"_AQUAFE_INCIDENT_FINAL_COMMIT={self.commit!r}\n"
                "_AQUAFE_INCIDENT_CLEAN_SUCCESS="
                "{'action':'write-once','exit_code':0}\n"
            )
        elif behavior == "system_exit":
            code = "raise SystemExit(0)\n"
        elif behavior == "exception":
            code = "raise RuntimeError('injected inner exception')\n"
        else:
            raise AssertionError(behavior)
        source.write_text(code, encoding="utf-8")
        return source

    def command(self, source: Path) -> list[str]:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return [
            "/usr/bin/python3.8", "-I", "-B", "-c", builder._CARRIER_SOURCE,
            str(source), digest, "--action", "write-once",
            "--successor-governor-sha256", "a" * 64,
            "--successor-governor-size-bytes", "1",
            "--v3-job-hash", self.job_hash,
        ]

    def run(self, *, behavior: str = "commit", after_pending=None,
            timeout: float = 20.0) -> subprocess.CompletedProcess[bytes]:
        source = self.write_fake_builder(behavior)
        process = subprocess.Popen(
            self.command(source), cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if after_pending is not None:
            deadline = time.monotonic() + timeout
            while not os.path.lexists(self.pending):
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    raise AssertionError(
                        "carrier exited before hidden-link fault injection: "
                        f"rc={process.returncode} stdout={stdout!r} "
                        f"stderr={stderr[-2000:]!r}")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise AssertionError("carrier hidden pending link timed out")
                time.sleep(0.0005)
            after_pending()
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(
            process.args, process.returncode, stdout, stderr)


class RuntimeAliasIncidentBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        successor_bytes = builder.SUCCESSOR.read_bytes()
        cls.successor_sha = hashlib.sha256(successor_bytes).hexdigest()
        cls.successor_size = len(successor_bytes)
        cls.namespace = builder._successor_contract(
            sha256=cls.successor_sha, size_bytes=cls.successor_size)
        source_bytes = SOURCE.read_bytes()
        cls.builder_identity = {
            "path": str(SOURCE), "size_bytes": len(source_bytes),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
        cls.record = builder.expected_incident_record_v1(
            successor_sha256=cls.successor_sha,
            successor_size_bytes=cls.successor_size,
            v3_job_hash=cls.namespace["job_hash"],
            builder_identity=cls.builder_identity,
            successor_namespace_contract=cls.namespace)

    def test_machine_namespace_remains_absent(self) -> None:
        self.assertFalse(builder.OUTPUT.exists())
        self.assertFalse(builder.PENDING_OUTPUT.exists())

    def test_exact_schema_hash_and_repair_authorities(self) -> None:
        validated = builder.validate_incident_record_v1(
            self.record, expected=self.record)
        self.assertEqual(set(validated), builder.INCIDENT_TOP_LEVEL_KEYS)
        diagnosis = validated["mechanical_runtime_alias_diagnosis"]
        self.assertEqual(
            set(diagnosis["authority"]), builder.DIAGNOSIS_AUTHORITY_KEYS)
        self.assertEqual(
            validated["successor_authorization"]["repair_policy"],
            builder.REPAIR_POLICY)
        execution = validated["builder_execution_contract"]
        self.assertEqual(execution["required_absent_at_commit_count"], 22)
        self.assertEqual(
            execution["required_absent_at_commit"],
            [str(path) for path in builder._absence_paths(
                self.namespace["job_hash"])])
        clone = copy.deepcopy(validated)
        clone["incident_hash"] = "0" * 64
        with_newline = hashlib.sha256(builder._canonical_bytes(clone)).hexdigest()
        without_newline = hashlib.sha256(
            builder._canonical_bytes(clone)[:-1]).hexdigest()
        self.assertEqual(validated["incident_hash"], with_newline)
        self.assertNotEqual(with_newline, without_newline)

    def test_every_scalar_leaf_is_exact_not_merely_self_hashed(self) -> None:
        paths = [path for path in _scalar_paths(self.record)
                 if path != ("incident_hash",)]
        self.assertGreater(len(paths), 100)
        for path in paths:
            with self.subTest(path=path):
                changed = copy.deepcopy(self.record)
                _replace_path(changed, path)
                changed["incident_hash"] = builder._self_hash(changed)
                with self.assertRaisesRegex(
                        builder.IncidentError, "exact expected tree differs"):
                    builder.validate_incident_record_v1(
                        changed, expected=self.record)

    def test_self_hash_mutation_is_rejected_before_exact_compare(self) -> None:
        changed = copy.deepcopy(self.record)
        changed["incident_hash"] = "f" * 64
        with self.assertRaisesRegex(builder.IncidentError, "self hash differs"):
            builder.validate_incident_record_v1(changed, expected=self.record)

    def test_live_v2_alias_and_optional_elf_evidence(self) -> None:
        holds = {
            label: {"data": Path(expected["path"]).read_bytes()}
            for label, expected in builder.EXPECTED_V2_FILES.items()
        }
        holds["v1_probe_intent"] = {"data": builder.V1_INTENT.read_bytes()}
        derived = builder._validate_runtime_alias_evidence(holds)
        self.assertEqual(
            derived["transitive_consumed_v1_evidence"],
            builder._transitive_v1_evidence())
        self.assertEqual(
            derived["runtime_closure_comparison"],
            builder._expected_runtime_closure_comparison())
        tbb = derived["probe_only_optional_elf"]
        self.assertEqual(set(tbb["file_identity"]["stat"]), {
            "device", "inode", "mode", "link_count", "uid", "gid",
            "mtime_ns", "ctime_ns",
        })
        self.assertIsNone(tbb["file_identity"]["symlink"])
        self.assertEqual(
            tbb["persistent_proc_maps"]["expected_rows"],
            builder.TBB_MAP_ROWS)
        self.assertEqual(
            tbb["native_loaded_elf_closure"]["expected_record"],
            builder.TBB_NATIVE_RECORD)
        changed = copy.deepcopy(holds)
        receipt = json.loads(changed["primary_runtime_receipt"]["data"])
        receipt["evaluator_rc"] = 1
        changed["primary_runtime_receipt"]["data"] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(
                builder.IncidentError, "evaluator terminal receipt differs"):
            builder._validate_runtime_alias_evidence(changed)

        changed = copy.deepcopy(holds)
        freeze = json.loads(changed["freeze"]["data"])
        expected = freeze["expected_runtime_closure"]["runtime_receipt"]
        tbb_file = next(
            row for row in expected["persistent_proc_maps"]["files"]
            if row["sha256"] == builder.TBB_FILE_IDENTITY["sha256"])
        tbb_file["stat"]["ctime_ns"] += 1
        changed["freeze"]["data"] = json.dumps(freeze).encode()
        with self.assertRaisesRegex(
                builder.IncidentError, "full typed records differ"):
            builder._validate_runtime_alias_evidence(changed)

        changed = copy.deepcopy(holds)
        receipt = json.loads(changed["primary_runtime_receipt"]["data"])
        receipt["persistent_proc_maps"]["files"].append(
            copy.deepcopy(builder.TBB_FILE_IDENTITY))
        changed["primary_runtime_receipt"]["data"] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(
                builder.IncidentError, "partial or whole probe-only"):
            builder._validate_runtime_alias_evidence(changed)

    def test_successor_contract_starts_no_process(self) -> None:
        def rejected(*_args, **_kwargs):
            raise AssertionError("process start attempted")

        with mock.patch.object(subprocess, "Popen", rejected), \
                mock.patch.object(subprocess, "run", rejected), \
                mock.patch.object(subprocess, "check_output", rejected):
            observed = builder._successor_contract(
                sha256=self.successor_sha, size_bytes=self.successor_size)
        self.assertEqual(observed, self.namespace)

    def test_atomic_carrier_and_fresh_namespace_contract(self) -> None:
        source = builder._CARRIER_SOURCE
        for required in (
            "O_TMPFILE", "os.fchmod(leaf,0o444)", "os.fsync(leaf)",
            "os.fsync(d)", "renameat2", "renameat2(d,os.fsencode(pending_name),d,os.fsencode(name),1)",
            "os._exit(0)", "no fallible Python operation follows",
            "required_records", "required_absent",
            "required_sibling_namespaces", ".pending_v1",
            "for item,parent_fd,chain,absent_name in absence_holds:",
            "os.stat(absent_name,dir_fd=parent_fd,follow_symlinks=False)",
            "incident builder final retained absence drifted",
        ):
            self.assertIn(required, source)
        absences = set(builder._absence_paths(self.namespace["job_hash"]))
        self.assertIn(builder.OUTPUT, absences)
        self.assertIn(builder.PENDING_OUTPUT, absences)
        self.assertIn(builder.V2_FAILURE, absences)
        self.assertIn(builder.V2_RESULT, absences)
        self.assertIn(builder.V2_POST, absences)
        self.assertIn(builder.V2_CLOSEOUT, absences)
        self.assertIn(builder.V3_RESULT, absences)
        self.assertIn(builder.V1_RESULT, absences)
        self.assertIn(builder.V1_FREEZE, absences)
        self.assertIn(builder.V1_FAILURE, absences)
        self.assertIn(builder.V1_POST, absences)
        self.assertTrue(set(builder._v1_publication_paths()).issubset(absences))
        self.assertEqual(len(absences), 22)
        self.assertEqual(
            len(builder._sibling_namespace_contracts(
                self.namespace["job_hash"])), 3)

    def test_each_transitive_v1_namespace_presence_is_rejected(self) -> None:
        legacy = (
            builder.V1_FREEZE, builder.V1_FAILURE, builder.V1_RESULT,
            builder.V1_POST, *builder._v1_publication_paths())
        self.assertEqual(len(set(legacy)), 7)
        for index, original in enumerate(legacy):
            with self.subTest(path=original), tempfile.TemporaryDirectory(
                    prefix="aqua-fe-incident-absence-test-") as temporary:
                present = Path(temporary) / f"{index}-{original.name}"
                present.touch()
                with self.assertRaisesRegex(
                        builder.IncidentError, "reserved namespace is present"):
                    with builder._hold_absences((present,)):
                        self.fail("present legacy namespace passed absence guard")

    def test_consumed_v1_intent_semantics_selfhash_and_identity(self) -> None:
        intent = builder._validate_v1_probe_intent(builder.V1_INTENT.read_bytes())
        self.assertEqual(
            intent["probe_launch_intent_hash"], builder.V1_INTENT_SELF_HASH)
        self.assertEqual(
            builder._authority_expected(
                builder.V1_INTENT, builder.EXPECTED_V1_INTENT["size_bytes"],
                builder.EXPECTED_V1_INTENT["sha256"]),
            {key: builder.EXPECTED_V1_INTENT[key]
             for key in ("path", "size_bytes", "sha256")})
        changed = copy.deepcopy(intent)
        changed["attempt_count"] = 2
        changed.pop("probe_launch_intent_hash")
        with self.assertRaisesRegex(
                builder.IncidentError, "semantics differ"):
            builder._validate_v1_probe_intent(json.dumps(changed).encode())

    def test_realpath_alias_rule_does_not_admit_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="aqua-fe-realpath-hardlink-") as temporary:
            original = Path(temporary) / "original"
            hardlink = Path(temporary) / "hardlink"
            original.write_bytes(b"same inode\n")
            os.link(original, hardlink)
            self.assertNotEqual(
                builder._realpath_alias(str(original), "original"),
                builder._realpath_alias(str(hardlink), "hardlink"))

    def test_live_publication_guard_exports_v1_record_and_22_absences(self) -> None:
        with builder.publication_guard(
                self.record, v3_job_hash=self.namespace["job_hash"]) as guard:
            guard["validate"]()
            self.assertEqual(len(guard["required_absent"]), 22)
            self.assertEqual(
                set(guard["required_absent"]),
                {str(path) for path in builder._absence_paths(
                    self.namespace["job_hash"])})
            records = {row["path"]: row for row in guard["required_records"]}
            self.assertEqual(
                records[str(builder.V1_INTENT)], builder.EXPECTED_V1_INTENT)

    def _carrier_output_is_governor_acceptable(self, path: Path) -> bool:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o444):
                return False
            value = json.loads(path.read_bytes())
            builder.validate_incident_record_v1(value, expected=self.record)
            return True
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError,
                builder.IncidentError):
            return False

    def test_real_outer_carrier_success_removes_pending(self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="aqua-fe-carrier-success-") as temporary:
            sandbox = _CarrierSandbox(Path(temporary),
                                      builder._pretty_bytes(self.record))
            result = sandbox.run()
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertTrue(
                self._carrier_output_is_governor_acceptable(sandbox.output))
            self.assertFalse(os.path.lexists(sandbox.pending))

    def test_real_outer_carrier_rejects_inner_exit_and_exception(self) -> None:
        for behavior in ("system_exit", "exception"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory(
                    prefix=f"aqua-fe-carrier-{behavior}-") as temporary:
                sandbox = _CarrierSandbox(
                    Path(temporary), builder._pretty_bytes(self.record))
                result = sandbox.run(behavior=behavior)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    self._carrier_output_is_governor_acceptable(sandbox.output))
                self.assertFalse(os.path.lexists(sandbox.pending))

    def test_real_outer_carrier_post_hidden_link_fault_matrix(self) -> None:
        def invalid_leaf(path: Path) -> None:
            path.write_bytes(b"{\"invalid\":true}\n")
            path.chmod(0o444)

        def inject(sandbox: _CarrierSandbox, fault: str) -> None:
            if fault == "unexpected_sibling":
                parent = Path(sandbox.siblings[1]["parent"])
                invalid_leaf(parent / (
                    ".formal900_r4_xfeatbirth_vs_gfttbirth_r2."
                    "unexpected.staging"))
            elif fault == "canonical_replacement":
                invalid_leaf(sandbox.output)
            elif fault == "required_absent_appearance":
                invalid_leaf(sandbox.extra_absent)
            elif fault == "pending_replacement":
                sandbox.pending.unlink()
                invalid_leaf(sandbox.pending)
            elif fault == "held_leaf_replacement":
                old = sandbox.target.with_name("held.old")
                sandbox.target.rename(old)
                invalid_leaf(sandbox.target)
            elif fault == "held_parent_replacement":
                moved = sandbox.volatile.with_name("volatile.old")
                sandbox.volatile.rename(moved)
                sandbox.volatile.mkdir()
                invalid_leaf(sandbox.volatile / "held.bin")
            else:
                raise AssertionError(fault)

        for fault in (
            "unexpected_sibling", "canonical_replacement",
            "required_absent_appearance", "pending_replacement",
            "held_leaf_replacement",
            "held_parent_replacement",
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory(
                    prefix=f"aqua-fe-carrier-{fault}-") as temporary:
                sandbox = _CarrierSandbox(
                    Path(temporary), builder._pretty_bytes(self.record))
                result = sandbox.run(
                    after_pending=lambda: inject(sandbox, fault))
                self.assertNotEqual(result.returncode, 0, fault)
                self.assertFalse(
                    self._carrier_output_is_governor_acceptable(sandbox.output),
                    fault)
                self.assertTrue(os.path.lexists(sandbox.pending), fault)
                pending_info = sandbox.pending.lstat()
                self.assertTrue(stat.S_ISREG(pending_info.st_mode), fault)
                self.assertEqual(stat.S_IMODE(pending_info.st_mode), 0o444, fault)


if __name__ == "__main__":
    unittest.main()
