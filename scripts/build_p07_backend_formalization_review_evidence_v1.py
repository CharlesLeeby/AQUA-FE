#!/usr/bin/env python3
"""Freeze post-adoption review evidence without authorizing scientific work.

The unplanned pre-outcome batch is first recorded by the incident document and
then administratively adopted through the frozen adoption workflow.  This
additive document closes the remaining review-evidence boundary: it binds the
published incident/adoption/review chain, precision and epoch authorities, the
complete future implementation/test snapshot, and two exact test receipts.

No payload produced here authorizes B0 materialization, replacement, backend
replay, G0 evaluation, ROS, VINS, APE, or RPE.  Every CLI action is read-only by
default and publication is explicit, no-clobber, root-anchored, and guarded by
retained input descriptors.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from functools import lru_cache
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping, Optional, Sequence

try:
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_incident_v1 as incident
    from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch
    from scripts import build_p07_backend_replay_queue_v1 as queue
    from scripts import p07_backend_formal_io_v1 as formal_io
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_incident_v1 as incident  # type: ignore
    import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore


ROOT = queue.ROOT
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_review_evidence_lock_v1.json"
)
SCHEMA = "isj-p07-backend-formalization-review-evidence-lock-v1"
STATUS = "FROZEN_POST_ADOPTION_REVIEW_EVIDENCE_NO_EXECUTION_AUTHORITY"
SELF_HASH_FIELD = "formalization_review_evidence_hash"
OUTCOME_BOUNDARY = (
    "PREOUTCOME_REVIEW_EVIDENCE_ONLY_NO_B0_REPLACEMENT_BACKEND_G0_ROS_VINS_APE_RPE"
)

PRECISION_LOCK_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "evaluator_precision_correction_lock_v1.json"
)
EPOCH_LOCK_RELATIVE = epoch.OUTPUT_RELATIVE

BUILDER_RELATIVE = "scripts/build_p07_backend_formalization_review_evidence_v1.py"
TEST_RELATIVE = "scripts/tests/test_p07_backend_formalization_review_evidence_v1.py"
LEAF_TEST_RELATIVE = "scripts/tests/test_p07_backend_formalization_review_leaf_v1.py"

# This base list is deliberately exact.  Runtime implementation paths are
# unioned lazily below so importing this governance module from the runtime
# validator cannot create a common <-> evidence initialization cycle.
_BASE_FUTURE_SOURCE_PATHS = tuple(
    sorted(
        {
            adoption.INCIDENT_BUILDER_RELATIVE,
            adoption.INCIDENT_TEST_RELATIVE,
            adoption.ADOPTION_BUILDER_RELATIVE,
            adoption.ADOPTION_TEST_RELATIVE,
            BUILDER_RELATIVE,
            TEST_RELATIVE,
            LEAF_TEST_RELATIVE,
            "scripts/build_p07_evaluator_precision_correction_lock_v1.py",
            "scripts/tests/test_p07_evaluator_precision_correction_lock_v1.py",
            "scripts/evaluate_vins_common_support.py",
            "scripts/trajectory_eval_core.py",
            "scripts/build_p07_evaluator_epoch_ns_correction_lock_v1.py",
            "scripts/tests/test_p07_evaluator_epoch_ns_correction_v1.py",
            "scripts/evaluate_vins_common_support_epoch_v2.py",
            "scripts/build_p07_backend_b0_formalization_adoption_bridge_v1.py",
            "scripts/run_p07_backend_b0_materialization_adopted_v1.py",
            "scripts/tests/test_p07_backend_b0_formalization_adoption_bridge_v1.py",
            "scripts/build_p07_backend_replacement_contract_v1.py",
            "scripts/allocate_p07_backend_replacement_v1.py",
            "scripts/tests/test_p07_backend_replacement_v1.py",
            "scripts/build_p07_g0_reference_contracts_v1.py",
            "scripts/build_p07_g0_evaluation_lock_v1.py",
            "scripts/p07_g0_governance_v1.py",
            "scripts/collect_p07_backend_failure_v1.py",
            "scripts/materialize_p07_g0_jobs_v1.py",
            "scripts/run_p07_g0_evaluation_v1.py",
            "scripts/reduce_p07_g0_results_v1.py",
            "scripts/p07_g0_publisher_v1.py",
            "scripts/tests/test_p07_g0_reference_rederivation_v1.py",
            "scripts/tests/test_p07_g0_governance_v1.py",
            "scripts/build_p07_backend_execution_lock_v1.py",
            "scripts/p07_backend_replay_common_v1.py",
            "scripts/p07_backend_sealed_runtime_v1.py",
            "scripts/run_p07_backend_serial_queue_v1.py",
            "scripts/run_p07_backend_replay_job_v1.py",
            "scripts/run_p07_backend_replay_adapter_v1.py",
            "scripts/audit_p07_backend_replay_v1.py",
            "scripts/check_p07_backend_replay_input_v1.py",
            "scripts/tests/test_p07_backend_execution_adoption_v1.py",
            "scripts/tests/test_p07_backend_formal_io_v1.py",
            "scripts/tests/test_p07_backend_replay_safety_v1.py",
            "scripts/tests/test_p07_backend_runtime_identity_v1.py",
            "scripts/tests/test_p07_backend_replay_only_v1.py",
        }
    )
)

RUNTIME_CONTRACT_DOCUMENT_PATHS = (
    "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json",
    "papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json",
)
_RUNTIME_SCRIPT_SUFFIXES = frozenset({".py", ".sh"})


@lru_cache(maxsize=1)
def _runtime_implementation_path_partitions() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Load common only on first use and classify its exact runtime closure."""

    try:
        from scripts import p07_backend_replay_common_v1 as replay_common
    except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
        import p07_backend_replay_common_v1 as replay_common  # type: ignore

    values = tuple(replay_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.values())
    if not values or len(values) != len(set(values)):
        raise ReviewEvidenceError("runtime implementation paths are empty or duplicate")
    scripts = tuple(
        sorted(path for path in values if PurePosixPath(path).suffix in _RUNTIME_SCRIPT_SUFFIXES)
    )
    contracts = tuple(
        sorted(path for path in values if PurePosixPath(path).suffix == ".json")
    )
    classified = set(scripts) | set(contracts)
    if classified != set(values):
        raise ReviewEvidenceError("runtime implementation path type is unclassified")
    if contracts != RUNTIME_CONTRACT_DOCUMENT_PATHS:
        raise ReviewEvidenceError("runtime contract document set drift")
    return scripts, contracts


@lru_cache(maxsize=1)
def _future_source_paths() -> tuple[str, ...]:
    runtime_scripts, _runtime_contracts = _runtime_implementation_path_partitions()
    return tuple(sorted(set(_BASE_FUTURE_SOURCE_PATHS) | set(runtime_scripts)))


class _LazyFutureSourcePaths(Sequence[str]):
    """Tuple-like compatibility view backed by the lazy runtime-source union."""

    def __getitem__(self, index: object) -> object:
        return _future_source_paths()[index]  # type: ignore[index]

    def __len__(self) -> int:
        return len(_future_source_paths())

    def __iter__(self) -> Iterator[str]:
        return iter(_future_source_paths())

    def __repr__(self) -> str:
        return repr(_future_source_paths())


FUTURE_SOURCE_PATHS: Sequence[str] = _LazyFutureSourcePaths()

RECEIPT_ROLES = (
    "GLOBAL_STABILITY_FULL_STACK",
    "INDEPENDENT_FRESH_REPLAY",
)
ADMINISTRATIVE_TEST_MODULES = adoption.ADMINISTRATIVE_TEST_MODULES
RECEIPT_KEYS = {
    "receipt_role",
    "reviewer_identity",
    "completed_at",
    "command_argv",
    "python_interpreter",
    "sealed_bootstrap",
    "test_methods",
    "aggregate_status",
    "tests_run",
    "return_code",
    "failures",
    "errors",
    "skipped",
    "stdout_sha256",
    "stderr_sha256",
    "source_artifacts_hash",
    "formal_write_performed",
    "vins_executed",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    "test_receipt_hash",
}
FULL_STACK_TEST_MODULES = (
    "scripts.tests.test_p07_backend_formal_io_v1",
    "scripts.tests.test_p07_backend_formalization_incident_v1",
    "scripts.tests.test_p07_backend_formalization_adoption_v1",
    "scripts.tests.test_p07_backend_formalization_review_leaf_v1",
    "scripts.tests.test_p07_backend_b0_formalization_adoption_bridge_v1",
    "scripts.tests.test_p07_backend_replacement_v1",
    "scripts.tests.test_p07_backend_execution_adoption_v1",
    "scripts.tests.test_p07_backend_replay_safety_v1",
    "scripts.tests.test_p07_backend_runtime_identity_v1",
    "scripts.tests.test_p07_g0_reference_rederivation_v1",
    "scripts.tests.test_p07_g0_governance_v1",
)
FULL_STACK_BOOTSTRAP = (
    "import sys,unittest;"
    "sys.path.insert(0,'/home/ma/AQUA-FE_WS');"
    "unittest.main(module=None,argv=['unittest',*sys.argv[1:]],verbosity=2)"
)
FULL_STACK_BOOTSTRAP_BYTES = FULL_STACK_BOOTSTRAP.encode("utf-8")
FULL_STACK_BOOTSTRAP_RECORD = {
    "sha256": hashlib.sha256(FULL_STACK_BOOTSTRAP_BYTES).hexdigest(),
    "size_bytes": len(FULL_STACK_BOOTSTRAP_BYTES),
}
FULL_STACK_ARGV = (
    adoption.SEALED_PYTHON_ARGV_TOKEN,
    "-I",
    adoption.SEALED_BOOTSTRAP_ARGV_TOKEN,
    *FULL_STACK_TEST_MODULES,
)
AUTHORITY_BINDING_KEYS = {"path", "sha256", "size_bytes", SELF_HASH_FIELD}
EVIDENCE_KEYS = {
    "schema_version",
    "status",
    "frozen_at",
    "formalization_adoption",
    "incident",
    "external_review_manifest",
    "global_stable_review",
    "independent_adoption_go",
    "scientific_authorities",
    "future_source_artifacts",
    "future_source_artifacts_hash",
    "test_receipts",
    "review_policy",
    "authorization",
    "publication_acknowledgements",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    SELF_HASH_FIELD,
}
SCIENTIFIC_AUTHORITY_KEYS = {
    "precision_correction_lock",
    "epoch_ns_correction_lock",
    "runtime_contract_documents",
}
ACKNOWLEDGEMENTS = {
    "review_evidence_only": True,
    "no_execution_authority": True,
}
AUTHORIZATION = {
    "b0_materialization_authorized": False,
    "replacement_authorized": False,
    "backend_replay_authorized": False,
    "g0_evaluation_authorized": False,
    "ros_authorized": False,
    "vins_authorized": False,
}


class ReviewEvidenceError(RuntimeError):
    """A review document or the post-adoption evidence lock is unsafe."""


class ReviewRollbackIncomplete(ReviewEvidenceError):
    """A failed review publication was preserved without automatic reclaim."""

    def __init__(self, rollback: adoption.RollbackIncomplete) -> None:
        self.retained_path = rollback.retained_path
        self.reason = rollback.reason
        self.retained_identity = rollback.retained_identity
        super().__init__(str(rollback))


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReviewEvidenceError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ReviewEvidenceError("timestamp must include a timezone")
    return parsed


def _hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(adoption.canonical_json(clone).encode("utf-8")).hexdigest()


def _file_record(root: Path, relative: str, *, label: str) -> dict[str, object]:
    try:
        content, record = adoption._read_direct(root.absolute(), relative, label=label)
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError(str(error)) from error
    if len(content) != int(record["size_bytes"]):
        raise ReviewEvidenceError(f"unstable {label}: {relative}")
    return dict(record)


def _strict_json(
    root: Path, relative: str, *, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        payload, record, _content = adoption._json_direct(
            root.absolute(), relative, label=label
        )
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError(str(error)) from error
    return payload, record


def _reference(
    record: Mapping[str, object], self_hash: str, field: str
) -> dict[str, object]:
    return {
        "path": record["path"],
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        field: self_hash,
    }


def _validate_reference_shape(
    value: object, *, path: str, field: str, label: str
) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256", "size_bytes", field}
        or value.get("path") != path
        or not adoption.HEX64.fullmatch(str(value.get("sha256", "")))
        or type(value.get("size_bytes")) is not int
        or int(value["size_bytes"]) <= 0
        or not adoption.HEX64.fullmatch(str(value.get(field, "")))
    ):
        raise ReviewEvidenceError(f"{label} reference shape mismatch")
    return dict(value)


def _source_records(root: Path) -> list[dict[str, object]]:
    return [
        _file_record(root, relative, label="reviewed future source")
        for relative in FUTURE_SOURCE_PATHS
    ]


def _runtime_contract_records(root: Path) -> list[dict[str, object]]:
    _runtime_scripts, runtime_contracts = _runtime_implementation_path_partitions()
    return [
        _file_record(root, relative, label="runtime contract authority")
        for relative in runtime_contracts
    ]


def _source_hash(records: Sequence[Mapping[str, object]]) -> str:
    return hashlib.sha256(adoption.canonical_json(list(records)).encode("utf-8")).hexdigest()


def _test_method_inventory(root: Path) -> list[str]:
    methods: list[str] = []
    for module in FULL_STACK_TEST_MODULES:
        relative = module.replace(".", "/") + ".py"
        try:
            content = formal_io.read_direct_bytes(root.absolute(), relative)[0]
            tree = ast.parse(content, filename=relative)
        except (OSError, SyntaxError, formal_io.FormalIOError) as error:
            raise ReviewEvidenceError(f"cannot derive test inventory: {relative}") from error
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    methods.append(f"{module}.{node.name}.{child.name}")
    result = sorted(methods)
    if not result or len(result) != len(set(result)):
        raise ReviewEvidenceError("full-stack test inventory is empty or duplicate")
    return result


def _sealed_memfd(content: bytes, *, name: str, executable: bool) -> int:
    required = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    if (
        not hasattr(os, "memfd_create")
        or not hasattr(os, "MFD_ALLOW_SEALING")
        or any(not hasattr(fcntl, item) for item in required)
    ):
        raise ReviewEvidenceError("sealed review runner is unsupported")
    flags = os.MFD_ALLOW_SEALING
    if hasattr(os, "MFD_CLOEXEC"):
        flags |= os.MFD_CLOEXEC
    descriptor = os.memfd_create(name, flags)
    try:
        formal_io._write_all(descriptor, content)
        if executable:
            os.fchmod(descriptor, 0o500)
        seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise ReviewEvidenceError("sealed review runner has incomplete seals")
        observed = bytearray()
        offset = 0
        while offset < len(content):
            chunk = os.pread(descriptor, min(1024 * 1024, len(content) - offset), offset)
            if not chunk:
                raise ReviewEvidenceError("sealed review runner copy is truncated")
            observed.extend(chunk)
            offset += len(chunk)
        if bytes(observed) != content:
            raise ReviewEvidenceError("sealed review runner copy differs")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _sanitized_test_environment() -> dict[str, str]:
    return {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AQUAFE_P07_REVIEW_RUNNER_DEPTH": "1",
    }


def _run_isolated_review_tests(
    *, root: Path, bootstrap: bytes, modules: Sequence[str]
) -> subprocess.CompletedProcess[bytes]:
    interpreter, _identity = formal_io.read_direct_bytes(
        Path("/"), adoption.ADMINISTRATIVE_PYTHON_INTERPRETER_RELATIVE
    )
    expected_record = adoption.administrative_python_interpreter_record()
    if (
        hashlib.sha256(interpreter).hexdigest() != expected_record["sha256"]
        or len(interpreter) != expected_record["size_bytes"]
    ):
        raise ReviewEvidenceError("isolated interpreter snapshot differs")
    with formal_io._retained_exact_leaf(
        Path("/"),
        adoption.ADMINISTRATIVE_PYTHON_INTERPRETER_RELATIVE,
        interpreter,
    ) as interpreter_lease:
        python_fd = _sealed_memfd(
            interpreter, name="aquafe_p07_review_python", executable=True
        )
        bootstrap_fd = _sealed_memfd(
            bootstrap, name="aquafe_p07_review_bootstrap", executable=False
        )
        try:
            formal_io._validate_retained_exact_leaf(interpreter_lease)
            completed = subprocess.run(
                [
                    f"/proc/self/fd/{python_fd}",
                    "-I",
                    f"/proc/self/fd/{bootstrap_fd}",
                    *[str(item) for item in modules],
                ],
                cwd=root,
                env=_sanitized_test_environment(),
                pass_fds=(python_fd, bootstrap_fd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            formal_io._validate_retained_exact_leaf(interpreter_lease)
            return completed
        finally:
            os.close(bootstrap_fd)
            os.close(python_fd)


def run_full_stack_tests(
    *,
    root: Path,
    receipt_role: str,
    reviewer_identity: Mapping[str, str],
    source_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if os.environ.get("AQUAFE_P07_REVIEW_RUNNER_DEPTH"):
        raise ReviewEvidenceError("nested full-stack test runner invocation forbidden")
    root = root.absolute()
    expected_methods = _test_method_inventory(root)
    source_hash = _source_hash(source_records)
    expected_bytes = {
        str(record["path"]): formal_io.read_direct_bytes(
            root, str(record["path"])
        )[0]
        for record in source_records
    }
    with ExitStack() as stack:
        leases = [
            stack.enter_context(
                formal_io._retained_exact_leaf(root, path, expected_bytes[path])
            )
            for path in sorted(expected_bytes)
        ]
        for lease in leases:
            formal_io._validate_retained_exact_leaf(lease)
        completed = _run_isolated_review_tests(
            root=root,
            bootstrap=FULL_STACK_BOOTSTRAP_BYTES,
            modules=FULL_STACK_TEST_MODULES,
        )
        for lease in leases:
            formal_io._validate_retained_exact_leaf(lease)
    stderr_text = completed.stderr.decode("utf-8", errors="strict")
    observed_methods = sorted(
        f"{match.group(2)}.{match.group(1)}"
        for match in re.finditer(
            r"^(\S+) \((scripts\.tests\.[^)]+)\) \.\.\. (?:ok|skipped .+)$",
            stderr_text,
            flags=re.MULTILINE,
        )
    )
    ran = re.search(r"^Ran (\d+) tests? in ", stderr_text, flags=re.MULTILINE)
    count = int(ran.group(1)) if ran else -1
    if (
        completed.returncode != 0
        or count != len(expected_methods)
        or observed_methods != expected_methods
    ):
        raise ReviewEvidenceError("full-stack review command did not pass exact inventory")
    return _build_test_receipt_from_execution(
        receipt_role=receipt_role,
        reviewer_identity=reviewer_identity,
        completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        command_argv=FULL_STACK_ARGV,
        test_methods=expected_methods,
        return_code=completed.returncode,
        stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
        source_artifacts_hash=source_hash,
        expected_test_methods=expected_methods,
    )


def _validate_reviewer_identity(
    value: object, *, role: str, label: str
) -> dict[str, str]:
    try:
        return adoption._validate_reviewer_identity(
            value, expected_role=role, label=label
        )
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError(str(error)) from error


def run_administrative_tests(
    *,
    root: Path,
    receipt_role: str,
    producer_identity: Mapping[str, str],
    candidate_source_bindings_hash: str,
    guard_paths: Sequence[str],
) -> dict[str, object]:
    """Run the exact outcome-blind governance modules and freeze their receipt."""

    if os.environ.get("AQUAFE_P07_REVIEW_RUNNER_DEPTH"):
        raise ReviewEvidenceError("nested administrative test runner invocation forbidden")
    argv = list(adoption.ADMINISTRATIVE_TEST_ARGV)
    root = root.absolute()
    expected = {
        path: formal_io.read_direct_bytes(root, path)[0] for path in guard_paths
    }
    records = [
        {
            "path": path,
            "sha256": hashlib.sha256(expected[path]).hexdigest(),
            "size_bytes": len(expected[path]),
        }
        for path in sorted(guard_paths)
    ]
    if _source_hash(records) != candidate_source_bindings_hash:
        raise ReviewEvidenceError("administrative test guard/source hash mismatch")
    with ExitStack() as stack:
        leases = [
            stack.enter_context(
                formal_io._retained_exact_leaf(root, path, expected[path])
            )
            for path in sorted(guard_paths)
        ]
        for lease in leases:
            formal_io._validate_retained_exact_leaf(lease)
        completed = _run_isolated_review_tests(
            root=root,
            bootstrap=adoption.ADMINISTRATIVE_TEST_BOOTSTRAP_BYTES,
            modules=adoption.ADMINISTRATIVE_TEST_MODULES,
        )
        for lease in leases:
            formal_io._validate_retained_exact_leaf(lease)
    stderr_text = completed.stderr.decode("utf-8", errors="strict")
    methods = sorted(
        set(
            f"{match.group(2)}.{match.group(1)}"
            for match in re.finditer(
                r"^(\S+) \((scripts\.tests\.[^)]+)\) \.\.\. (?:ok|skipped .+)$",
                stderr_text,
                flags=re.MULTILINE,
            )
        )
    )
    ran = re.search(r"^Ran (\d+) tests? in ", stderr_text, flags=re.MULTILINE)
    tests_run = int(ran.group(1)) if ran else -1
    if (
        completed.returncode != 0
        or tests_run != len(adoption.ADMINISTRATIVE_TEST_METHODS)
        or methods != list(adoption.ADMINISTRATIVE_TEST_METHODS)
    ):
        raise ReviewEvidenceError("administrative test command did not pass exactly")
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return adoption.build_administrative_test_receipt(
        receipt_role=receipt_role,
        completed_at=completed_at,
        producer_identity=producer_identity,
        command_argv=argv,
        test_methods=methods,
        tests_run=tests_run,
        return_code=completed.returncode,
        stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
        candidate_source_bindings_hash=candidate_source_bindings_hash,
    )


def test_receipt_hash(payload: Mapping[str, object]) -> str:
    return _hash(payload, "test_receipt_hash")


def _build_test_receipt_from_execution(
    *,
    receipt_role: str,
    reviewer_identity: Mapping[str, str],
    completed_at: str,
    command_argv: Sequence[str],
    test_methods: Sequence[str],
    return_code: int,
    stdout_sha256: str,
    stderr_sha256: str,
    source_artifacts_hash: str,
    expected_test_methods: Sequence[str],
) -> dict[str, object]:
    if receipt_role not in RECEIPT_ROLES:
        raise ReviewEvidenceError("unknown test receipt role")
    if list(test_methods) != list(expected_test_methods):
        raise ReviewEvidenceError("executed test methods differ from frozen inventory")
    _timestamp(completed_at)
    payload: dict[str, object] = {
        "receipt_role": receipt_role,
        "reviewer_identity": dict(reviewer_identity),
        "completed_at": completed_at,
        "command_argv": list(command_argv),
        "python_interpreter": adoption.administrative_python_interpreter_record(),
        "sealed_bootstrap": dict(FULL_STACK_BOOTSTRAP_RECORD),
        "test_methods": list(test_methods),
        "aggregate_status": "PASS",
        "tests_run": len(test_methods),
        "return_code": return_code,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "source_artifacts_hash": source_artifacts_hash,
        "formal_write_performed": False,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload["test_receipt_hash"] = test_receipt_hash(payload)
    validate_test_receipt(
        payload,
        source_artifacts_hash=source_artifacts_hash,
        expected_test_methods=expected_test_methods,
    )
    return payload


def validate_test_receipt(
    payload: Mapping[str, object],
    *,
    source_artifacts_hash: str,
    expected_test_methods: Sequence[str],
) -> str:
    role = str(payload.get("receipt_role", ""))
    expected_reviewer_role = (
        adoption.GLOBAL_REVIEWER_ROLE
        if role == RECEIPT_ROLES[0]
        else adoption.INDEPENDENT_REVIEWER_ROLE
    )
    if (
        set(payload) != RECEIPT_KEYS
        or role not in RECEIPT_ROLES
        or payload.get("test_receipt_hash") != test_receipt_hash(payload)
        or payload.get("aggregate_status") != "PASS"
        or type(payload.get("tests_run")) is not int
        or int(payload["tests_run"]) <= 0
        or any(payload.get(field) != 0 for field in ("failures", "errors"))
        or type(payload.get("skipped")) is not int
        or int(payload["skipped"]) < 0
        or payload.get("source_artifacts_hash") != source_artifacts_hash
        or payload.get("formal_write_performed") is not False
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise ReviewEvidenceError("test receipt semantic/hash mismatch")
    _timestamp(str(payload.get("completed_at", "")))
    _validate_reviewer_identity(
        payload.get("reviewer_identity"), role=expected_reviewer_role, label=role
    )
    argv = payload.get("command_argv")
    methods = payload.get("test_methods")
    if (
        argv != list(FULL_STACK_ARGV)
        or payload.get("python_interpreter")
        != adoption.administrative_python_interpreter_record()
        or payload.get("sealed_bootstrap") != FULL_STACK_BOOTSTRAP_RECORD
        or not isinstance(methods, list)
        or not methods
        or methods != list(expected_test_methods)
        or int(payload["tests_run"]) != len(methods)
        or payload.get("return_code") != 0
        or not adoption.HEX64.fullmatch(str(payload.get("stdout_sha256", "")))
        or not adoption.HEX64.fullmatch(str(payload.get("stderr_sha256", "")))
    ):
        raise ReviewEvidenceError("test receipt exact command/method inventory mismatch")
    return str(payload["test_receipt_hash"])


def _build_external_manifest_from_receipt(
    *,
    root: Path = ROOT,
    frozen_at: str,
    administrative_test_receipt: Mapping[str, object],
) -> dict[str, object]:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(
        root, incident.OUTPUT_RELATIVE, label="formalization incident"
    )
    try:
        incident_hash = incident.validate_incident(
            incident_payload, root=root, verify_live=False
        )
    except incident.IncidentError as error:
        raise ReviewEvidenceError("incident historical validation failed") from error
    if _timestamp(frozen_at) < _timestamp(str(incident_payload.get("observed_at", ""))):
        raise ReviewEvidenceError("external manifest predates incident")
    governance_records = [
        _file_record(root, relative, label="external review governance")
        for relative in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS
    ]
    governance_hash = hashlib.sha256(
        adoption.canonical_json(governance_records).encode("utf-8")
    ).hexdigest()
    adoption._validate_administrative_test_receipt(
        administrative_test_receipt,
        expected_role="EXTERNAL_MANIFEST_PREFLIGHT",
        expected_source_bindings_hash=governance_hash,
    )
    payload: dict[str, object] = {
        "schema_version": adoption.EXTERNAL_REVIEW_MANIFEST_SCHEMA,
        "status": adoption.EXTERNAL_REVIEW_MANIFEST_STATUS,
        "frozen_at": frozen_at,
        "incident": _reference(
            incident_record, incident_hash, incident.SELF_HASH_FIELD
        ),
        "governance_artifacts": governance_records,
        "review_protocol": (
            "TWO_DISTINCT_REVIEWERS_GLOBAL_THEN_INDEPENDENT_BEFORE_ADOPTION"
        ),
        "review_scope": "PREOUTCOME_BYTE_EXACT_ADMINISTRATIVE_ADOPTION_ONLY",
        "reviewer_role_requirements": {
            "required_roles": [
                adoption.GLOBAL_REVIEWER_ROLE,
                adoption.INDEPENDENT_REVIEWER_ROLE,
            ],
            "distinct_reviewer_identities_required": True,
            "independent_review_must_bind_global_review": True,
        },
        "administrative_test_receipt": dict(administrative_test_receipt),
        "publication_acknowledgements": {
            "external_review_manifest_only": True,
            "no_execution_authority": True,
        },
        "execution_authorized": False,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": adoption.OUTCOME_BOUNDARY,
    }
    payload[adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD] = adoption.document_hash(
        payload, adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
    )
    validate_external_manifest(payload, root=root, verify_files=True)
    return payload


def build_external_manifest(
    *,
    root: Path = ROOT,
    frozen_at: str,
    producer_identity: Mapping[str, str],
    ack_external_review_manifest_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    if not ack_external_review_manifest_only or not ack_no_execution_authority:
        raise ReviewEvidenceError(
            "external manifest build requires both non-authorizing acknowledgements"
        )
    root = root.absolute()
    records = [
        _file_record(root, relative, label="external review governance")
        for relative in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS
    ]
    source_hash = _source_hash(records)
    receipt = run_administrative_tests(
        root=root,
        receipt_role="EXTERNAL_MANIFEST_PREFLIGHT",
        producer_identity=producer_identity,
        candidate_source_bindings_hash=source_hash,
        guard_paths=adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS,
    )
    return _build_external_manifest_from_receipt(
        root=root,
        frozen_at=frozen_at,
        administrative_test_receipt=receipt,
    )


def validate_external_manifest(
    payload: Mapping[str, object], *, root: Path = ROOT, verify_files: bool = True
) -> str:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(
        root, incident.OUTPUT_RELATIVE, label="formalization incident"
    )
    try:
        incident_hash = incident.validate_incident(
            incident_payload, root=root, verify_live=False
        )
        result = adoption._validate_external_review_manifest(
            payload,
            incident_reference=_reference(
                incident_record, incident_hash, incident.SELF_HASH_FIELD
            ),
            root=root,
            verify_files=verify_files,
        )
    except (incident.IncidentError, adoption.AdoptionError) as error:
        raise ReviewEvidenceError("external review manifest validation failed") from error
    if _timestamp(str(payload.get("frozen_at", ""))) < _timestamp(
        str(incident_payload.get("observed_at", ""))
    ):
        raise ReviewEvidenceError("external manifest predates incident")
    return result


def _load_review_chain(root: Path) -> dict[str, tuple[dict[str, object], dict[str, object]]]:
    return {
        "incident": _strict_json(root, incident.OUTPUT_RELATIVE, label="incident"),
        "manifest": _strict_json(
            root, adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, label="external manifest"
        ),
        "global": _strict_json(
            root, adoption.GLOBAL_STABLE_REVIEW_RELATIVE, label="global review"
        ),
        "independent": _strict_json(
            root, adoption.INDEPENDENT_GO_RELATIVE, label="independent GO"
        ),
        "adoption": _strict_json(root, adoption.OUTPUT_RELATIVE, label="adoption"),
    }


def _build_global_review_from_receipt(
    *,
    root: Path = ROOT,
    reviewed_at: str,
    reviewer_identity: Mapping[str, str],
    administrative_test_receipt: Mapping[str, object],
) -> dict[str, object]:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(root, incident.OUTPUT_RELATIVE, label="incident")
    incident_hash = incident.validate_incident(incident_payload, root=root, verify_live=False)
    manifest, manifest_record = _strict_json(
        root, adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, label="external manifest"
    )
    manifest_hash = validate_external_manifest(manifest, root=root, verify_files=True)
    live = adoption.collect_live_rebuild_evidence(root=root)
    source_hash = str(live["source_bindings_hash"])
    identity = _validate_reviewer_identity(
        reviewer_identity, role=adoption.GLOBAL_REVIEWER_ROLE, label="global review"
    )
    adoption._validate_administrative_test_receipt(
        administrative_test_receipt,
        expected_role="GLOBAL_STABILITY_ADMINISTRATIVE",
        expected_source_bindings_hash=source_hash,
    )
    payload: dict[str, object] = {
        "schema_version": adoption.GLOBAL_STABLE_SCHEMA,
        "status": adoption.GLOBAL_STABLE_STATUS,
        "reviewed_at": reviewed_at,
        "reviewer_identity": identity,
        "independence_attestation": dict(adoption.GLOBAL_INDEPENDENCE_ATTESTATION),
        "incident": _reference(incident_record, incident_hash, incident.SELF_HASH_FIELD),
        "external_review_manifest": _reference(
            manifest_record,
            manifest_hash,
            adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        ),
        "candidate_source_bindings_hash": source_hash,
        "tests_status": "PASS",
        "administrative_test_receipt": dict(administrative_test_receipt),
        "publication_acknowledgements": {
            "global_stability_review_only": True,
            "no_execution_authority": True,
        },
        "formal_write_performed": False,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": adoption.OUTCOME_BOUNDARY,
    }
    payload[adoption.GLOBAL_STABLE_HASH_FIELD] = adoption.document_hash(
        payload, adoption.GLOBAL_STABLE_HASH_FIELD
    )
    adoption._validate_global_stable_review(
        payload,
        incident_reference=payload["incident"],
        manifest_reference=payload["external_review_manifest"],
        source_bindings_hash=source_hash,
    )
    return payload


def build_global_review(
    *,
    root: Path = ROOT,
    reviewed_at: str,
    reviewer_identity: Mapping[str, str],
    ack_global_stability_review_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    if not ack_global_stability_review_only or not ack_no_execution_authority:
        raise ReviewEvidenceError(
            "global review build requires both non-authorizing acknowledgements"
        )
    root = root.absolute()
    live = adoption.collect_live_rebuild_evidence(root=root)
    source_records = live.get("source_artifacts")
    if not isinstance(source_records, list):
        raise ReviewEvidenceError("global review candidate source list missing")
    receipt = run_administrative_tests(
        root=root,
        receipt_role="GLOBAL_STABILITY_ADMINISTRATIVE",
        producer_identity=reviewer_identity,
        candidate_source_bindings_hash=str(live["source_bindings_hash"]),
        guard_paths=[str(item["path"]) for item in source_records],
    )
    return _build_global_review_from_receipt(
        root=root,
        reviewed_at=reviewed_at,
        reviewer_identity=reviewer_identity,
        administrative_test_receipt=receipt,
    )


def _build_independent_go_from_receipt(
    *,
    root: Path = ROOT,
    reviewed_at: str,
    reviewer_identity: Mapping[str, str],
    administrative_test_receipt: Mapping[str, object],
) -> dict[str, object]:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(root, incident.OUTPUT_RELATIVE, label="incident")
    incident_hash = incident.validate_incident(incident_payload, root=root, verify_live=False)
    manifest, manifest_record = _strict_json(
        root, adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, label="external manifest"
    )
    manifest_hash = validate_external_manifest(manifest, root=root, verify_files=True)
    global_payload, global_record = _strict_json(
        root, adoption.GLOBAL_STABLE_REVIEW_RELATIVE, label="global review"
    )
    live = adoption.collect_live_rebuild_evidence(root=root)
    source_hash = str(live["source_bindings_hash"])
    global_hash = adoption._validate_global_stable_review(
        global_payload,
        incident_reference=_reference(incident_record, incident_hash, incident.SELF_HASH_FIELD),
        manifest_reference=_reference(
            manifest_record, manifest_hash, adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
        ),
        source_bindings_hash=source_hash,
    )
    global_identity = _validate_reviewer_identity(
        global_payload.get("reviewer_identity"),
        role=adoption.GLOBAL_REVIEWER_ROLE,
        label="global review",
    )
    identity = _validate_reviewer_identity(
        reviewer_identity,
        role=adoption.INDEPENDENT_REVIEWER_ROLE,
        label="independent review",
    )
    adoption._validate_administrative_test_receipt(
        administrative_test_receipt,
        expected_role="INDEPENDENT_ADMINISTRATIVE_REPLAY",
        expected_source_bindings_hash=source_hash,
    )
    if _timestamp(str(global_payload["reviewed_at"])) >= _timestamp(reviewed_at):
        raise ReviewEvidenceError("independent review must follow global review")
    payload: dict[str, object] = {
        "schema_version": adoption.INDEPENDENT_GO_SCHEMA,
        "status": adoption.INDEPENDENT_GO_STATUS,
        "reviewed_at": reviewed_at,
        "reviewer_identity": identity,
        "independence_attestation": {
            "global_reviewer_id": global_identity["reviewer_id"],
            "global_reviewer_instance": global_identity["reviewer_instance"],
            "independent_reviewer_is_global_reviewer": False,
            "incident_creator_is_reviewer": False,
            "review_performed_without_outcome_access": True,
            "execution_authority_requested": False,
        },
        "incident": _reference(incident_record, incident_hash, incident.SELF_HASH_FIELD),
        "external_review_manifest": _reference(
            manifest_record, manifest_hash, adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
        ),
        "global_stable_review": _reference(
            global_record, global_hash, adoption.GLOBAL_STABLE_HASH_FIELD
        ),
        "candidate_source_bindings_hash": source_hash,
        "administrative_test_receipt": dict(administrative_test_receipt),
        "publication_acknowledgements": {
            "independent_adoption_review_only": True,
            "no_execution_authority": True,
        },
        "adoption_scope": "ADMINISTRATIVE_ADOPTION_ONLY_NO_EXECUTION",
        "execution_authorized": False,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": adoption.OUTCOME_BOUNDARY,
    }
    payload[adoption.INDEPENDENT_GO_HASH_FIELD] = adoption.document_hash(
        payload, adoption.INDEPENDENT_GO_HASH_FIELD
    )
    adoption._validate_independent_go(
        payload,
        incident_reference=payload["incident"],
        manifest_reference=payload["external_review_manifest"],
        global_reference=payload["global_stable_review"],
        global_reviewer_identity=global_identity,
        source_bindings_hash=source_hash,
    )
    return payload


def build_independent_go(
    *,
    root: Path = ROOT,
    reviewed_at: str,
    reviewer_identity: Mapping[str, str],
    ack_independent_adoption_review_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    if (
        not ack_independent_adoption_review_only
        or not ack_no_execution_authority
    ):
        raise ReviewEvidenceError(
            "independent review build requires both non-authorizing acknowledgements"
        )
    root = root.absolute()
    live = adoption.collect_live_rebuild_evidence(root=root)
    source_records = live.get("source_artifacts")
    if not isinstance(source_records, list):
        raise ReviewEvidenceError("independent review candidate source list missing")
    receipt = run_administrative_tests(
        root=root,
        receipt_role="INDEPENDENT_ADMINISTRATIVE_REPLAY",
        producer_identity=reviewer_identity,
        candidate_source_bindings_hash=str(live["source_bindings_hash"]),
        guard_paths=[str(item["path"]) for item in source_records],
    )
    return _build_independent_go_from_receipt(
        root=root,
        reviewed_at=reviewed_at,
        reviewer_identity=reviewer_identity,
        administrative_test_receipt=receipt,
    )


REVIEW_STAGE_ABSENT_PATHS = tuple(
    dict.fromkeys(
        (
            *incident.GLOBAL_PREOUTCOME_ABSENT_PATHS,
            OUTPUT_RELATIVE,
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_prelock_v1.json",
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_action_intent_v1.json",
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_closeout_v1.json",
        )
    )
)


def _require_review_stage_absence(
    root: Path, *, allowed_present: Sequence[str]
) -> None:
    allowed = set(allowed_present)
    for relative in REVIEW_STAGE_ABSENT_PATHS:
        if relative in allowed:
            continue
        try:
            present = formal_io.destination_exists(root.absolute(), relative)
        except formal_io.FormalIOError as error:
            raise ReviewEvidenceError(
                f"review-stage path is not direct/inspectable: {relative}"
            ) from error
        if present:
            raise ReviewEvidenceError(
                f"review-stage downstream path already exists: {relative}"
            )


def _validate_external_publish_state(
    payload: Mapping[str, object], *, root: Path, incident_live: bool
) -> None:
    root = root.absolute()
    incident_payload, _record = _strict_json(
        root, incident.OUTPUT_RELATIVE, label="formalization incident"
    )
    try:
        incident.validate_incident(
            incident_payload, root=root, verify_live=incident_live
        )
    except incident.IncidentError as error:
        raise ReviewEvidenceError("incident review-stage validation failed") from error
    validate_external_manifest(payload, root=root, verify_files=True)
    _require_review_stage_absence(
        root,
        allowed_present=(
            (adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,) if not incident_live else ()
        ),
    )


def validate_global_review(
    payload: Mapping[str, object], *, root: Path = ROOT
) -> str:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(
        root, incident.OUTPUT_RELATIVE, label="formalization incident"
    )
    try:
        incident_hash = incident.validate_incident(
            incident_payload, root=root, verify_live=False
        )
    except incident.IncidentError as error:
        raise ReviewEvidenceError("global review incident validation failed") from error
    manifest_payload, manifest_record = _strict_json(
        root, adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, label="external manifest"
    )
    manifest_hash = validate_external_manifest(
        manifest_payload, root=root, verify_files=True
    )
    live = adoption.collect_live_rebuild_evidence(root=root)
    try:
        result = adoption._validate_global_stable_review(
            payload,
            incident_reference=_reference(
                incident_record, incident_hash, incident.SELF_HASH_FIELD
            ),
            manifest_reference=_reference(
                manifest_record,
                manifest_hash,
                adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
            ),
            source_bindings_hash=str(live["source_bindings_hash"]),
        )
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError("global review semantic validation failed") from error
    if not (
        _timestamp(str(incident_payload["observed_at"]))
        <= _timestamp(str(manifest_payload["frozen_at"]))
        <= _timestamp(str(payload.get("reviewed_at", "")))
    ):
        raise ReviewEvidenceError("global review timestamp order mismatch")
    return result


def validate_independent_go(
    payload: Mapping[str, object], *, root: Path = ROOT
) -> str:
    root = root.absolute()
    incident_payload, incident_record = _strict_json(
        root, incident.OUTPUT_RELATIVE, label="formalization incident"
    )
    try:
        incident_hash = incident.validate_incident(
            incident_payload, root=root, verify_live=False
        )
    except incident.IncidentError as error:
        raise ReviewEvidenceError("independent review incident validation failed") from error
    manifest_payload, manifest_record = _strict_json(
        root, adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, label="external manifest"
    )
    manifest_hash = validate_external_manifest(
        manifest_payload, root=root, verify_files=True
    )
    global_payload, global_record = _strict_json(
        root, adoption.GLOBAL_STABLE_REVIEW_RELATIVE, label="global review"
    )
    global_hash = validate_global_review(global_payload, root=root)
    global_identity = _validate_reviewer_identity(
        global_payload.get("reviewer_identity"),
        role=adoption.GLOBAL_REVIEWER_ROLE,
        label="global review",
    )
    live = adoption.collect_live_rebuild_evidence(root=root)
    try:
        result = adoption._validate_independent_go(
            payload,
            incident_reference=_reference(
                incident_record, incident_hash, incident.SELF_HASH_FIELD
            ),
            manifest_reference=_reference(
                manifest_record,
                manifest_hash,
                adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
            ),
            global_reference=_reference(
                global_record, global_hash, adoption.GLOBAL_STABLE_HASH_FIELD
            ),
            global_reviewer_identity=global_identity,
            source_bindings_hash=str(live["source_bindings_hash"]),
        )
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError("independent review semantic validation failed") from error
    if _timestamp(str(global_payload["reviewed_at"])) >= _timestamp(
        str(payload.get("reviewed_at", ""))
    ):
        raise ReviewEvidenceError("independent review timestamp order mismatch")
    return result


def _build_evidence_lock_from_receipts(
    *,
    root: Path = ROOT,
    frozen_at: str,
    test_receipts: Sequence[Mapping[str, object]],
    ack_review_evidence_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    root = root.absolute()
    if not ack_review_evidence_only or not ack_no_execution_authority:
        raise ReviewEvidenceError("evidence lock requires both non-authorizing acknowledgements")
    adoption_payload, adoption_record = adoption.load_and_validate_historical_adoption(root=root)
    chain = _load_review_chain(root)
    source_records = _source_records(root)
    source_hash = _source_hash(source_records)
    expected_methods = _test_method_inventory(root)
    if len(test_receipts) != 2 or [item.get("receipt_role") for item in test_receipts] != list(RECEIPT_ROLES):
        raise ReviewEvidenceError("evidence lock requires ordered global and independent receipts")
    for receipt in test_receipts:
        validate_test_receipt(
            receipt,
            source_artifacts_hash=source_hash,
            expected_test_methods=expected_methods,
        )
    global_identity = chain["global"][0].get("reviewer_identity")
    independent_identity = chain["independent"][0].get("reviewer_identity")
    if (
        test_receipts[0].get("reviewer_identity") != global_identity
        or test_receipts[1].get("reviewer_identity") != independent_identity
    ):
        raise ReviewEvidenceError("test receipt/review identity mismatch")
    precision_record = _file_record(root, PRECISION_LOCK_RELATIVE, label="precision correction lock")
    epoch_payload, epoch_record = _strict_json(root, EPOCH_LOCK_RELATIVE, label="epoch correction lock")
    runtime_contract_records = _runtime_contract_records(root)
    try:
        epoch_hash = epoch.validate_lock_payload(epoch_payload, root=root, verify_files=True)
    except ValueError as error:
        raise ReviewEvidenceError("epoch correction semantic validation failed") from error
    precision_parent = epoch_payload.get("parent_precision_correction_lock")
    if not isinstance(precision_parent, dict) or any(
        precision_parent.get(key) != precision_record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise ReviewEvidenceError("epoch/precision authority relation mismatch")
    refs = {
        "incident": (incident.SELF_HASH_FIELD, incident.OUTPUT_RELATIVE),
        "manifest": (
            adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
            adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        ),
        "global": (adoption.GLOBAL_STABLE_HASH_FIELD, adoption.GLOBAL_STABLE_REVIEW_RELATIVE),
        "independent": (adoption.INDEPENDENT_GO_HASH_FIELD, adoption.INDEPENDENT_GO_RELATIVE),
    }
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "formalization_adoption": {
            "path": adoption.OUTPUT_RELATIVE,
            "sha256": adoption_record["sha256"],
            "size_bytes": adoption_record["size_bytes"],
            adoption.SELF_HASH_FIELD: adoption_payload[adoption.SELF_HASH_FIELD],
        },
        "incident": _reference(chain["incident"][1], str(chain["incident"][0][refs["incident"][0]]), refs["incident"][0]),
        "external_review_manifest": _reference(chain["manifest"][1], str(chain["manifest"][0][refs["manifest"][0]]), refs["manifest"][0]),
        "global_stable_review": _reference(chain["global"][1], str(chain["global"][0][refs["global"][0]]), refs["global"][0]),
        "independent_adoption_go": _reference(chain["independent"][1], str(chain["independent"][0][refs["independent"][0]]), refs["independent"][0]),
        "scientific_authorities": {
            "precision_correction_lock": precision_record,
            "epoch_ns_correction_lock": _reference(
                epoch_record, epoch_hash, epoch.SELF_HASH_FIELD
            ),
            "runtime_contract_documents": runtime_contract_records,
        },
        "future_source_artifacts": source_records,
        "future_source_artifacts_hash": source_hash,
        "test_receipts": [dict(item) for item in test_receipts],
        "review_policy": {
            "two_distinct_reviewers_required": True,
            "fresh_global_and_independent_test_receipts_required": True,
            "future_source_hashes_frozen_before_b0_or_replacement": True,
            "future_authorities_must_bind_adoption_and_this_lock": True,
        },
        "authorization": dict(AUTHORIZATION),
        "publication_acknowledgements": dict(ACKNOWLEDGEMENTS),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH_FIELD] = _hash(payload, SELF_HASH_FIELD)
    validate_evidence_lock(payload, root=root, verify_files=True)
    return payload


def build_evidence_lock(
    *,
    root: Path = ROOT,
    frozen_at: str,
    ack_review_evidence_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    """Run both fixed full-stack suites and build the post-adoption lock."""

    if not ack_review_evidence_only or not ack_no_execution_authority:
        raise ReviewEvidenceError(
            "evidence lock requires both non-authorizing acknowledgements before tests"
        )
    root = root.absolute()
    source_records = _source_records(root)
    chain = _load_review_chain(root)
    global_identity = chain["global"][0].get("reviewer_identity")
    independent_identity = chain["independent"][0].get("reviewer_identity")
    if not isinstance(global_identity, dict) or not isinstance(independent_identity, dict):
        raise ReviewEvidenceError("adopted review identities are missing")
    receipts = [
        run_full_stack_tests(
            root=root,
            receipt_role=RECEIPT_ROLES[0],
            reviewer_identity=global_identity,
            source_records=source_records,
        ),
        run_full_stack_tests(
            root=root,
            receipt_role=RECEIPT_ROLES[1],
            reviewer_identity=independent_identity,
            source_records=source_records,
        ),
    ]
    return _build_evidence_lock_from_receipts(
        root=root,
        frozen_at=frozen_at,
        test_receipts=receipts,
        ack_review_evidence_only=ack_review_evidence_only,
        ack_no_execution_authority=ack_no_execution_authority,
    )


def validate_evidence_lock(
    payload: Mapping[str, object], *, root: Path = ROOT, verify_files: bool = True
) -> str:
    if (
        set(payload) != EVIDENCE_KEYS
        or payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != _hash(payload, SELF_HASH_FIELD)
        or payload.get("review_policy")
        != {
            "two_distinct_reviewers_required": True,
            "fresh_global_and_independent_test_receipts_required": True,
            "future_source_hashes_frozen_before_b0_or_replacement": True,
            "future_authorities_must_bind_adoption_and_this_lock": True,
        }
        or payload.get("authorization") != AUTHORIZATION
        or payload.get("publication_acknowledgements") != ACKNOWLEDGEMENTS
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise ReviewEvidenceError("review evidence schema/status/hash drift")
    frozen_at = _timestamp(str(payload.get("frozen_at", "")))
    _validate_reference_shape(
        payload.get("formalization_adoption"),
        path=adoption.OUTPUT_RELATIVE,
        field=adoption.SELF_HASH_FIELD,
        label="adoption",
    )
    reference_specs = (
        ("incident", incident.OUTPUT_RELATIVE, incident.SELF_HASH_FIELD),
        ("external_review_manifest", adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD),
        ("global_stable_review", adoption.GLOBAL_STABLE_REVIEW_RELATIVE, adoption.GLOBAL_STABLE_HASH_FIELD),
        ("independent_adoption_go", adoption.INDEPENDENT_GO_RELATIVE, adoption.INDEPENDENT_GO_HASH_FIELD),
    )
    for name, path, field in reference_specs:
        _validate_reference_shape(payload.get(name), path=path, field=field, label=name)
    authorities = payload.get("scientific_authorities")
    if not isinstance(authorities, dict) or set(authorities) != SCIENTIFIC_AUTHORITY_KEYS:
        raise ReviewEvidenceError("scientific authority key set mismatch")
    precision = authorities.get("precision_correction_lock")
    if (
        not isinstance(precision, dict)
        or set(precision) != {"path", "sha256", "size_bytes"}
        or precision.get("path") != PRECISION_LOCK_RELATIVE
    ):
        raise ReviewEvidenceError("precision correction record mismatch")
    _validate_reference_shape(
        authorities.get("epoch_ns_correction_lock"),
        path=EPOCH_LOCK_RELATIVE,
        field=epoch.SELF_HASH_FIELD,
        label="epoch correction",
    )
    runtime_contracts = authorities.get("runtime_contract_documents")
    if (
        not isinstance(runtime_contracts, list)
        or [item.get("path") for item in runtime_contracts if isinstance(item, dict)]
        != list(RUNTIME_CONTRACT_DOCUMENT_PATHS)
    ):
        raise ReviewEvidenceError("runtime contract authority set mismatch")
    try:
        adoption._validate_file_records(
            runtime_contracts, label="runtime contract authorities"
        )
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError("runtime contract authority records malformed") from error
    records = payload.get("future_source_artifacts")
    if (
        not isinstance(records, list)
        or [item.get("path") for item in records if isinstance(item, dict)] != list(FUTURE_SOURCE_PATHS)
        or payload.get("future_source_artifacts_hash") != _source_hash(records)
    ):
        raise ReviewEvidenceError("future source artifact set/hash mismatch")
    try:
        adoption._validate_file_records(records, label="future source artifacts")
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError("future source records malformed") from error
    receipts = payload.get("test_receipts")
    if not isinstance(receipts, list) or [item.get("receipt_role") for item in receipts if isinstance(item, dict)] != list(RECEIPT_ROLES):
        raise ReviewEvidenceError("test receipt role/order mismatch")
    expected_methods = _test_method_inventory(root.absolute())
    for receipt in receipts:
        validate_test_receipt(
            receipt,
            source_artifacts_hash=str(payload["future_source_artifacts_hash"]),
            expected_test_methods=expected_methods,
        )
    receipt_times = [_timestamp(str(item["completed_at"])) for item in receipts]
    adopted_at = None
    if verify_files:
        adopted_payload, _adopted_record = _strict_json(
            root.absolute(), adoption.OUTPUT_RELATIVE, label="adoption timestamp authority"
        )
        adopted_at = _timestamp(str(adopted_payload.get("adopted_at", "")))
    if (
        receipt_times[0] >= receipt_times[1]
        or receipt_times[1] > frozen_at
        or (adopted_at is not None and adopted_at > receipt_times[0])
    ):
        raise ReviewEvidenceError("test receipt/evidence timestamp order mismatch")
    if verify_files:
        root = root.absolute()
        adoption_binding = adoption.adoption_authority_binding(root=root)
        if payload.get("formalization_adoption") != adoption_binding:
            raise ReviewEvidenceError("review evidence adoption authority drift")
        chain = _load_review_chain(root)
        adoption_payload = chain["adoption"][0]
        exact_refs = {
            "incident": adoption_payload["incident"],
            "external_review_manifest": adoption_payload["external_review_manifest"],
            "global_stable_review": adoption_payload["global_stable_review"],
            "independent_adoption_go": adoption_payload["independent_adoption_go"],
        }
        for name, _path, _field in reference_specs:
            if payload.get(name) != exact_refs[name]:
                raise ReviewEvidenceError(f"review evidence {name} differs from adoption")
        review_chain = adoption_payload.get("review_chain")
        if not isinstance(review_chain, dict):
            raise ReviewEvidenceError("adoption review chain missing")
        if (
            receipts[0].get("reviewer_identity") != review_chain.get("global_reviewer_identity")
            or receipts[1].get("reviewer_identity") != review_chain.get("independent_reviewer_identity")
            or _timestamp(str(review_chain.get("independent_reviewed_at", ""))) > receipt_times[1]
        ):
            raise ReviewEvidenceError("test receipts do not bind the adopted reviewers")
        for record in records:
            observed = _file_record(root, str(record["path"]), label="future source")
            if observed != record:
                raise ReviewEvidenceError(f"future source drift: {record['path']}")
        observed_precision = _file_record(root, PRECISION_LOCK_RELATIVE, label="precision lock")
        if observed_precision != precision:
            raise ReviewEvidenceError("precision correction bytes drift")
        if _runtime_contract_records(root) != runtime_contracts:
            raise ReviewEvidenceError("runtime contract authority bytes drift")
        epoch_payload, epoch_record = _strict_json(root, EPOCH_LOCK_RELATIVE, label="epoch lock")
        try:
            epoch_hash = epoch.validate_lock_payload(epoch_payload, root=root, verify_files=True)
        except ValueError as error:
            raise ReviewEvidenceError("epoch correction semantic drift") from error
        if authorities["epoch_ns_correction_lock"] != _reference(
            epoch_record, epoch_hash, epoch.SELF_HASH_FIELD
        ):
            raise ReviewEvidenceError("epoch correction authority drift")
        parent = epoch_payload.get("parent_precision_correction_lock")
        if not isinstance(parent, dict) or any(
            parent.get(key) != precision.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise ReviewEvidenceError("epoch parent/precision binding drift")
    return str(payload[SELF_HASH_FIELD])


def load_and_validate_historical_evidence(
    root: Path = ROOT,
) -> tuple[dict[str, object], dict[str, object]]:
    payload, record = _strict_json(root.absolute(), OUTPUT_RELATIVE, label="review evidence lock")
    validate_evidence_lock(payload, root=root.absolute(), verify_files=True)
    return payload, record


def review_evidence_authority_binding(root: Path = ROOT) -> dict[str, object]:
    payload, record = load_and_validate_historical_evidence(root=root)
    return _reference(record, str(payload[SELF_HASH_FIELD]), SELF_HASH_FIELD)


def validate_review_evidence_authority_binding(
    value: object, *, root: Path = ROOT
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != AUTHORITY_BINDING_KEYS:
        raise ReviewEvidenceError("review evidence authority key set mismatch")
    expected = review_evidence_authority_binding(root=root)
    if value != expected:
        raise ReviewEvidenceError("review evidence authority live mismatch")
    return dict(value)


def _guard_paths_for_payload(payload: Mapping[str, object]) -> list[str]:
    paths = {
        incident.OUTPUT_RELATIVE,
        adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
        adoption.INDEPENDENT_GO_RELATIVE,
        adoption.OUTPUT_RELATIVE,
        PRECISION_LOCK_RELATIVE,
        EPOCH_LOCK_RELATIVE,
        *FUTURE_SOURCE_PATHS,
        *RUNTIME_CONTRACT_DOCUMENT_PATHS,
    }
    return sorted(paths)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _publish_transaction(
    payload: Mapping[str, object],
    *,
    root: Path,
    relative: str,
    validate: Callable[[], None],
    post_validate: Optional[Callable[[], None]] = None,
    guard_paths: Sequence[str],
    pre_link_hook: Optional[Callable[[], None]] = None,
    post_link_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    root = root.absolute()
    content = adoption.json_bytes(payload)
    with formal_io.global_formal_lock():
        if formal_io.destination_exists(root, relative):
            raise FileExistsError(relative)
        expected = {
            path: formal_io.read_direct_bytes(root, path)[0] for path in guard_paths
        }
        with ExitStack() as stack:
            leases = [
                stack.enter_context(formal_io._retained_exact_leaf(root, path, expected[path]))
                for path in guard_paths
            ]

            def validate_snapshot(check: Callable[[], None]) -> None:
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)
                check()
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)

            validate_snapshot(validate)
            with formal_io._parent_dirfd(root, relative) as (parent_fd, name):
                parent_path = (root / relative).parent.absolute()
                adoption._assert_no_preserved_rollback(
                    parent_fd=parent_fd, name=name, parent_path=parent_path
                )
                try:
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(relative)
                temporary = f".{name}.partial.{os.getpid()}.{secrets.token_hex(12)}"
                temp_fd = -1
                staged: Optional[os.stat_result] = None
                linked = False
                temp_present = False
                pending_rollback: Optional[ReviewRollbackIncomplete] = None
                try:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
                    temp_fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                    temp_present = True
                    formal_io._write_all(temp_fd, content)
                    os.fsync(temp_fd)
                    staged = os.fstat(temp_fd)
                    if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1 or staged.st_size != len(content):
                        raise ReviewEvidenceError("staged review evidence identity mismatch")
                    if pre_link_hook is not None:
                        pre_link_hook()
                    validate_snapshot(validate)
                    adoption._assert_no_preserved_rollback(
                        parent_fd=parent_fd, name=name, parent_path=parent_path
                    )
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    linked = True
                    formal_io._fsync_directory(parent_fd)
                    os.unlink(temporary, dir_fd=parent_fd)
                    temp_present = False
                    formal_io._fsync_directory(parent_fd)
                    if post_link_hook is not None:
                        post_link_hook()
                    validate_snapshot(post_validate or validate)
                    observed, opened = formal_io._read_direct_at(parent_fd, name)
                    reachable = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        staged is None
                        or not _same_inode(staged, opened)
                        or not _same_inode(staged, reachable)
                        or opened.st_nlink != 1
                        or observed != content
                    ):
                        raise ReviewEvidenceError("published review evidence drift")
                except BaseException as transaction_error:
                    if linked and staged is not None:
                        try:
                            adoption._preserve_own_destination_rollback(
                                parent_fd=parent_fd,
                                name=name,
                                parent_path=parent_path,
                                staged=staged,
                                retained_fd=temp_fd,
                            )
                        except adoption.RollbackIncomplete as rollback_error:
                            pending_rollback = ReviewRollbackIncomplete(rollback_error)
                            raise pending_rollback from transaction_error
                    raise
                finally:
                    if temp_fd >= 0:
                        os.close(temp_fd)
                    if temp_present:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
                        try:
                            formal_io._fsync_directory(parent_fd)
                        except OSError:
                            if pending_rollback is None:
                                raise
                    if pending_rollback is not None:
                        adoption._finalize_pending_rollback_identity(
                            pending_rollback,
                            parent_fd=parent_fd,
                            parent_path=parent_path,
                        )
                if staged is None or not linked:
                    raise ReviewEvidenceError("review evidence was not linked")
                return {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "device": staged.st_dev,
                    "inode": staged.st_ino,
                }


def _review_stage_guard_paths(
    root: Path, *, additional: Sequence[str]
) -> list[str]:
    paths = {
        incident.OUTPUT_RELATIVE,
        incident.REGISTRY_RELATIVE,
        *incident.PRESENT_PATHS,
        *adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS,
        *additional,
    }
    try:
        live = adoption.collect_live_rebuild_evidence(root=root.absolute())
    except adoption.AdoptionError as error:
        raise ReviewEvidenceError("cannot establish review-stage live snapshot") from error
    records = live.get("source_artifacts")
    if not isinstance(records, list):
        raise ReviewEvidenceError("review-stage source artifact list is missing")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ReviewEvidenceError("review-stage source artifact record is malformed")
        paths.add(str(record["path"]))
    return sorted(paths)


def publish_external_manifest(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    ack_external_review_manifest_only: bool,
    ack_no_execution_authority: bool,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    if not ack_external_review_manifest_only or not ack_no_execution_authority:
        raise ReviewEvidenceError("external manifest publication requires both acknowledgements")
    if payload.get("publication_acknowledgements") != {
        "external_review_manifest_only": True,
        "no_execution_authority": True,
    }:
        raise ReviewEvidenceError("external manifest payload lacks acknowledgements")
    root = root.absolute()
    return _publish_transaction(
        payload,
        root=root,
        relative=adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        validate=lambda: _validate_external_publish_state(
            payload, root=root, incident_live=True
        ),
        post_validate=lambda: _validate_external_publish_state(
            payload, root=root, incident_live=False
        ),
        guard_paths=_review_stage_guard_paths(root, additional=()),
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def publish_global_review(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    ack_global_stability_review_only: bool,
    ack_no_execution_authority: bool,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    if not ack_global_stability_review_only or not ack_no_execution_authority:
        raise ReviewEvidenceError("global review publication requires both acknowledgements")
    if payload.get("publication_acknowledgements") != {
        "global_stability_review_only": True,
        "no_execution_authority": True,
    }:
        raise ReviewEvidenceError("global review payload lacks acknowledgements")
    root = root.absolute()

    def pre_validate() -> None:
        validate_global_review(payload, root=root)
        _require_review_stage_absence(
            root, allowed_present=(adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,)
        )

    def post_validate() -> None:
        validate_global_review(payload, root=root)
        _require_review_stage_absence(
            root,
            allowed_present=(
                adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
                adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
            ),
        )

    return _publish_transaction(
        payload,
        root=root,
        relative=adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
        validate=pre_validate,
        post_validate=post_validate,
        guard_paths=_review_stage_guard_paths(
            root, additional=(adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,)
        ),
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def publish_independent_go(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    ack_independent_adoption_review_only: bool,
    ack_no_execution_authority: bool,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    if (
        not ack_independent_adoption_review_only
        or not ack_no_execution_authority
    ):
        raise ReviewEvidenceError("independent review publication requires both acknowledgements")
    if payload.get("publication_acknowledgements") != {
        "independent_adoption_review_only": True,
        "no_execution_authority": True,
    }:
        raise ReviewEvidenceError("independent review payload lacks acknowledgements")
    root = root.absolute()

    def pre_validate() -> None:
        validate_independent_go(payload, root=root)
        _require_review_stage_absence(
            root,
            allowed_present=(
                adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
                adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
            ),
        )

    def post_validate() -> None:
        validate_independent_go(payload, root=root)
        _require_review_stage_absence(
            root,
            allowed_present=(
                adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
                adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
                adoption.INDEPENDENT_GO_RELATIVE,
            ),
        )

    return _publish_transaction(
        payload,
        root=root,
        relative=adoption.INDEPENDENT_GO_RELATIVE,
        validate=pre_validate,
        post_validate=post_validate,
        guard_paths=_review_stage_guard_paths(
            root,
            additional=(
                adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
                adoption.GLOBAL_STABLE_REVIEW_RELATIVE,
            ),
        ),
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def publish_evidence_lock(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    ack_review_evidence_only: bool,
    ack_no_execution_authority: bool,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    if not ack_review_evidence_only or not ack_no_execution_authority:
        raise ReviewEvidenceError("publication API requires both acknowledgements")
    if payload.get("publication_acknowledgements") != ACKNOWLEDGEMENTS:
        raise ReviewEvidenceError("payload lacks both publication acknowledgements")
    return _publish_transaction(
        payload,
        root=root,
        relative=OUTPUT_RELATIVE,
        validate=lambda: validate_evidence_lock(payload, root=root, verify_files=True),
        guard_paths=_guard_paths_for_payload(payload),
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument(
        "--action",
        choices=("external-manifest", "global-review", "independent-go", "evidence-lock"),
        default="evidence-lock",
    )
    parser.add_argument("--reviewer-id")
    parser.add_argument("--reviewer-instance")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--ack-external-review-manifest-only", action="store_true")
    parser.add_argument("--ack-global-stability-review-only", action="store_true")
    parser.add_argument("--ack-independent-adoption-review-only", action="store_true")
    parser.add_argument("--ack-review-evidence-only", action="store_true")
    parser.add_argument("--ack-no-execution-authority", action="store_true")
    args = parser.parse_args()
    role_by_action = {
        "external-manifest": "EXTERNAL_MANIFEST_BUILDER",
        "global-review": adoption.GLOBAL_REVIEWER_ROLE,
        "independent-go": adoption.INDEPENDENT_REVIEWER_ROLE,
    }
    if args.action in role_by_action and (
        not args.reviewer_id or not args.reviewer_instance
    ):
        parser.error("review-stage actions require reviewer id and instance")
    identity = None
    if args.action in role_by_action:
        identity = {
            "reviewer_id": args.reviewer_id,
            "reviewer_instance": args.reviewer_instance,
            "reviewer_role": role_by_action[args.action],
        }
    try:
        if args.action == "external-manifest":
            payload = build_external_manifest(
                root=args.root.absolute(),
                frozen_at=args.frozen_at,
                producer_identity=identity or {},
                ack_external_review_manifest_only=args.ack_external_review_manifest_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
            relative = adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE
            hash_field = adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
        elif args.action == "global-review":
            payload = build_global_review(
                root=args.root.absolute(),
                reviewed_at=args.frozen_at,
                reviewer_identity=identity or {},
                ack_global_stability_review_only=args.ack_global_stability_review_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
            relative = adoption.GLOBAL_STABLE_REVIEW_RELATIVE
            hash_field = adoption.GLOBAL_STABLE_HASH_FIELD
        elif args.action == "independent-go":
            payload = build_independent_go(
                root=args.root.absolute(),
                reviewed_at=args.frozen_at,
                reviewer_identity=identity or {},
                ack_independent_adoption_review_only=args.ack_independent_adoption_review_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
            relative = adoption.INDEPENDENT_GO_RELATIVE
            hash_field = adoption.INDEPENDENT_GO_HASH_FIELD
        else:
            payload = build_evidence_lock(
                root=args.root.absolute(),
                frozen_at=args.frozen_at,
                ack_review_evidence_only=args.ack_review_evidence_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
            relative = OUTPUT_RELATIVE
            hash_field = SELF_HASH_FIELD
    except (OSError, ReviewEvidenceError) as error:
        print(json.dumps({
            "mode": "FORMAL_WRITE_BLOCKED" if args.write else "READ_ONLY_BLOCKED",
            "status": "BLOCKED_AWAITING_ADOPTION_AND_REVIEW_EVIDENCE",
            "reason": str(error),
            "execution_authorized": False,
        }, indent=2, sort_keys=True))
        return 2
    if args.write:
        if args.action == "external-manifest":
            publish_external_manifest(
                payload,
                root=args.root.absolute(),
                ack_external_review_manifest_only=args.ack_external_review_manifest_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
        elif args.action == "global-review":
            publish_global_review(
                payload,
                root=args.root.absolute(),
                ack_global_stability_review_only=args.ack_global_stability_review_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
        elif args.action == "independent-go":
            publish_independent_go(
                payload,
                root=args.root.absolute(),
                ack_independent_adoption_review_only=args.ack_independent_adoption_review_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
        else:
            publish_evidence_lock(
                payload,
                root=args.root.absolute(),
                ack_review_evidence_only=args.ack_review_evidence_only,
                ack_no_execution_authority=args.ack_no_execution_authority,
            )
        mode = "FORMAL_NON_AUTHORIZING_REVIEW_STAGE_FROZEN"
    else:
        mode = "READ_ONLY_PREVIEW"
    print(json.dumps({
        "mode": mode,
        "action": args.action,
        "path": relative,
        hash_field: payload[hash_field],
        "execution_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
