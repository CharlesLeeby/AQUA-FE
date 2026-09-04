#!/usr/bin/env python3
"""Fail-closed one-shot Phase-F HFNet runner for frozen AQUALOC H03 [90,180).

The runner is deliberately dataset- and attempt-specific.  Its only execution
action requires an exact token, an immutable execution lock, a fresh O_EXCL
start claim, and permits one Popen invocation with no retry.  Input, settings,
model, cache seed, official stack, and the resolved ELF dependency closure are
audited before and after the child is synchronously reaped.

This is an exploratory underwater-usability run.  It cannot establish accuracy
or superiority over another frontend or learning system.
"""

from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import zlib


ROOT = Path(__file__).resolve().parents[1]

ROLE = "PHASE_F_FRESH_H03_EXPLORATORY_UNDERWATER_USABILITY_ONLY"
DEPENDENCY_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-dependency-inventory-v1"
PREFLIGHT_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-preflight-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-prepared-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-execution-lock-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-prestart-check-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-process-start-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-run-result-v1"

AUTHORIZATION_TOKEN = "PHASE_F_H03_1800_3600_ATTEMPT_001_START_ONCE"
TIMEOUT_SECONDS = 900
RC_OK = 0
RC_FAILED = 1
RC_BLOCKED = 2

CAMERA_COUNT = 1_801
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 512
PREROLL_FIRST_INDEX = 0
PREROLL_LAST_INDEX = 899
SCORE_FIRST_INDEX = 900
SCORE_LAST_INDEX = 1_800
MAX_ASSOCIATION_ERROR_NS = 256
QUATERNION_NORM_TOLERANCE = 0.001
MIN_LAST_CAMERA_INDEX = 1_620
MIN_SCORE_POSES = 20
MIN_CONTIGUOUS_SCORE_POSES = 20
MIN_SCORE_KEYFRAMES = 1

OFFICIAL_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
OFFICIAL_TREE = "6619814aed4cd0e4baa2501341a48f753f8ba196"
OFFICIAL_ORIGIN = "https://github.com/LiuLimingCode/HFNet_SLAM.git"

OFFICIAL_ROOT = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1")
BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
BUILD_MANIFEST = BINARY.parent / "build_manifest.json"
OFFICIAL_LIBRARY = OFFICIAL_ROOT / "lib/libHFNet_SLAM.so"
OFFICIAL_ENTRY = OFFICIAL_ROOT / "Examples/Monocular-Inertial/mono_inertial_euroc.cc"
HEADLESS_SOURCE = ROOT / "scripts/harnesses/hfnet_slam_mono_inertial_euroc_headless_v3.cc"
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_h03_1800_3600_phase_f_v1.yaml"
PASSED_STACK_LOCK = ROOT / "papers/hfnet_v6_passed_stack_lock_v1.json"
SELECTOR = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_selector_freeze_v1.json"
MATERIALIZER = ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
MATERIALIZER_TEST = ROOT / "scripts/tests/test_materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
INPUT_AUDITOR = ROOT / "scripts/audit_hfnet_v6_phase_f_h03_1800_3600_input_v1.py"
PREPARATION_AUDIT = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_preparation_audit_v1.json"
RUNNER_TEST = ROOT / "scripts/tests/test_run_hfnet_v6_phase_f_h03_1800_3600_v1.py"
SHARED_MODEL_DIR = Path("/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT")
ONNX = SHARED_MODEL_DIR / "HF-Net.onnx"
CACHE = SHARED_MODEL_DIR / "HF-Net.cache"
RUNTIME_ROOT = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
PANGOLIN_ROOT = Path("/home/ma/SLAM/aqua_deps/install")
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_phase_f_fresh_underwater_v1/"
    "aqualoc_harbor_h03_1800_3600"
)
ATTEMPT = ROOT / "logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_harbor_h03_1800_3600/attempt_001"
DEPENDENCY_INVENTORY = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_dependency_inventory_v1.json"
EXECUTION_LOCK = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_execution_lock_v1.json"

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "passed_stack_lock": {"size_bytes": 8_111, "sha256": "cb826526a28f28e77f546d4647e16fd19426494e9a15ab01108301136cbfadad"},
    "selector": {"size_bytes": 12_536, "sha256": "ab7557db88d884e565d71a31a562e3e88c70eba6d8e643f22ca5b2bdd2d18269"},
    "materializer": {"size_bytes": 38_774, "sha256": "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d"},
    "materializer_test": {"size_bytes": 11_666, "sha256": "02e5af45ee05b7d192d30a7461c57de4a2c8e4a0a90238961e7bae6a2c45ea86"},
    "input_auditor": {"size_bytes": 18_347, "sha256": "674d8ee097216125b900410d589d97d01442a66d2fa3f02ae196e5ff86f0c170"},
    "preparation_audit": {"size_bytes": 3_379, "sha256": "5f989732ca936c1a75f5227576eaf152ff4515b8ff0ca757024583224a19d775"},
    "config": {"size_bytes": 2_257, "sha256": "3ed0e32354049edfaf7c42edaeed3baf7a25e994ec29fab3135b5edef053f5ab"},
    "binary": {"size_bytes": 118_280, "sha256": "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb"},
    "build_manifest": {"size_bytes": 1_748, "sha256": "dc01d34652afbeb9dfd8b64e96b7d3ecdd8a09522796b73207a05e295ca4f8e9"},
    "official_library": {"size_bytes": 4_807_712, "sha256": "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717"},
    "official_entry": {"size_bytes": 10_201, "sha256": "fa3effb0c2b99bc4dd83abda443180cf2f017f61710e02fa6b3f9278cc774d39"},
    "headless_source": {"size_bytes": 1_112, "sha256": "303947840bdc5377656554560c6785b3218a52e034862a63d5d6da0036b81d90"},
    "onnx": {"size_bytes": 132_238_602, "sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5"},
    "cache": {"size_bytes": 853_319, "sha256": "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7"},
}

EXPECTED_FULL_INPUT = {
    "file_count": 1_805,
    "total_bytes": 331_333_378,
    "tree_sha256": "b3980d27873df053226d7459e738c3c08d9b9d0e76658410306ce6f369b2b5b0",
    "tree_crc32": "f2c100c1",
}

BASE_MODEL_PATH_LINE = 'Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"'


class ContractError(RuntimeError):
    """Raised on any identity, namespace, process, or one-shot violation."""


@dataclass(frozen=True)
class Spec:
    official_root: Path = OFFICIAL_ROOT
    binary: Path = BINARY
    build_manifest: Path = BUILD_MANIFEST
    official_library: Path = OFFICIAL_LIBRARY
    official_entry: Path = OFFICIAL_ENTRY
    headless_source: Path = HEADLESS_SOURCE
    config: Path = CONFIG
    passed_stack_lock: Path = PASSED_STACK_LOCK
    selector: Path = SELECTOR
    materializer: Path = MATERIALIZER
    materializer_test: Path = MATERIALIZER_TEST
    input_auditor: Path = INPUT_AUDITOR
    preparation_audit: Path = PREPARATION_AUDIT
    onnx: Path = ONNX
    cache: Path = CACHE
    runtime_root: Path = RUNTIME_ROOT
    pangolin_root: Path = PANGOLIN_ROOT
    input_root: Path = INPUT_ROOT
    attempt: Path = ATTEMPT
    dependency_inventory: Path = DEPENDENCY_INVENTORY
    execution_lock: Path = EXECUTION_LOCK
    timeout_seconds: int = TIMEOUT_SECONDS
    expected: Mapping[str, Mapping[str, object]] = field(default_factory=lambda: EXPECTED_IDENTITIES)

    @property
    def model_dir(self) -> Path:
        return self.attempt / "run_local_model/HFNet-RT"

    @property
    def local_onnx(self) -> Path:
        return self.model_dir / "HF-Net.onnx"

    @property
    def local_cache(self) -> Path:
        return self.model_dir / "HF-Net.cache"

    @property
    def runtime_config(self) -> Path:
        return self.attempt / "runtime_config_model_path_only.yaml"

    @property
    def prepared_manifest(self) -> Path:
        return self.attempt / "prepared_manifest.json"

    @property
    def start_claim(self) -> Path:
        return self.attempt / "process_start_claim.json"

    @property
    def stdout_log(self) -> Path:
        return self.attempt / "headless.stdout.log"

    @property
    def stderr_log(self) -> Path:
        return self.attempt / "headless.stderr.log"

    @property
    def result_dir(self) -> Path:
        return self.attempt / "result"

    @property
    def run_result(self) -> Path:
        return self.attempt / "run_result.json"


DEFAULT_SPEC = Spec()


@dataclass(frozen=True)
class Execution:
    popen_invocations: int
    process_started: bool
    pid: Optional[int]
    returncode: Optional[int]
    timed_out: bool
    synchronously_reaped: bool
    duration_seconds: float
    termination_signals: Tuple[str, ...] = ()
    error: Optional[str] = None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path, *, recorded_path: Optional[Path] = None) -> Dict[str, object]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ContractError("NOT_REGULAR_NONSYMLINK_FILE:%s" % path)
    return {
        "path": str(absolute(recorded_path or path)),
        "size_bytes": metadata.st_size,
        "sha256": sha256_file(path),
    }


def content_identity(path: Path) -> Dict[str, object]:
    observed = file_identity(path)
    return {"size_bytes": observed["size_bytes"], "sha256": observed["sha256"]}


def require_identity(path: Path, expected: Mapping[str, object], label: str) -> Dict[str, object]:
    observed = file_identity(path)
    if observed["size_bytes"] != expected.get("size_bytes") or observed["sha256"] != expected.get("sha256"):
        raise ContractError("FROZEN_IDENTITY_MISMATCH:%s" % label)
    return observed


def read_canonical_json(path: Path) -> object:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if raw != canonical_json(value):
        raise ContractError("JSON_NOT_CANONICAL:%s" % path)
    return value


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(str(path), mode)


def fsync_dir(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def runtime_library_paths(spec: Spec) -> Tuple[Path, ...]:
    return (
        spec.official_root / "lib",
        spec.official_root / "Thirdparty/g2o/lib",
        spec.pangolin_root / "lib",
        spec.runtime_root / "usr/lib/x86_64-linux-gnu",
        spec.runtime_root / "usr/local/cuda-11.6/lib64",
        spec.runtime_root / "usr/local/cuda-11.6/targets/x86_64-linux/lib",
        spec.runtime_root / "usr/local/cuda-11.8/lib64",
        spec.runtime_root / "usr/local/cuda-11.8/targets/x86_64-linux/lib",
    )


def runtime_environment(spec: Spec) -> Dict[str, str]:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/home/ma",
        "USER": "ma",
        "CUDA_VISIBLE_DEVICES": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "LD_LIBRARY_PATH": ":".join(str(absolute(path)) for path in runtime_library_paths(spec)),
    }


def command_argv(spec: Spec) -> List[str]:
    return [
        str(absolute(spec.binary)),
        str(absolute(spec.runtime_config)),
        str(absolute(spec.result_dir)).rstrip("/") + "/",
        str(absolute(spec.input_root)),
        str(absolute(spec.input_root / "cam0_times.txt")),
    ]


def _command(command: Sequence[str], *, cwd: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> str:
    environment = dict(os.environ)
    if env:
        environment.update(env)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        done = subprocess.run(
            list(command), cwd=str(cwd) if cwd else None, env=environment,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContractError("READ_ONLY_COMMAND_FAILED:%s:%s" % (command[0], type(error).__name__)) from error
    if done.returncode != 0:
        raise ContractError("READ_ONLY_COMMAND_RC:%s:%s:%s" % (command[0], done.returncode, done.stderr.strip()[:240]))
    return done.stdout


def _elf_metadata(spec: Spec) -> Dict[str, Any]:
    output = _command(["readelf", "-d", str(spec.binary)], env=runtime_environment(spec))
    needed = sorted(re.findall(r"\(NEEDED\).*?\[(.*?)\]", output))
    runpaths = re.findall(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]", output)
    if len(runpaths) != 1 or not needed:
        raise ContractError("ELF_DYNAMIC_METADATA_INVALID")
    return {"direct_needed": needed, "runpath": runpaths[0]}


def build_dependency_core(spec: Spec) -> Dict[str, Any]:
    output = _command(["ldd", str(spec.binary)], env=runtime_environment(spec))
    if "not found" in output:
        raise ContractError("ELF_DEPENDENCY_NOT_FOUND")
    aliases: Dict[str, set] = {}
    for line in output.splitlines():
        match = re.match(r"^\s*(\S+)\s+=>\s+(/\S+)\s+\(", line)
        if match:
            soname, lexical = match.group(1), match.group(2)
        else:
            match = re.match(r"^\s*(/\S+)\s+\(", line)
            if not match:
                continue
            lexical = match.group(1)
            soname = Path(lexical).name
        resolved = str(Path(lexical).resolve(strict=True))
        aliases.setdefault(resolved, set()).add(soname)
    if not aliases:
        raise ContractError("ELF_DEPENDENCY_SET_EMPTY")
    records: List[Dict[str, Any]] = []
    for resolved in sorted(aliases):
        item = file_identity(Path(resolved))
        item["sonames"] = sorted(aliases[resolved])
        records.append(item)
    digest_payload = canonical_json(records)
    return {
        "binary": require_identity(spec.binary, spec.expected["binary"], "binary"),
        "elf": _elf_metadata(spec),
        "ld_library_path": runtime_environment(spec)["LD_LIBRARY_PATH"],
        "dependency_count": len(records),
        "dependency_total_bytes": sum(int(row["size_bytes"]) for row in records),
        "dependency_records_sha256": hashlib.sha256(digest_payload).hexdigest(),
        "dependencies": records,
    }


def snapshot_dependencies(spec: Spec = DEFAULT_SPEC) -> Dict[str, Any]:
    errors: List[str] = []
    written = None
    try:
        if spec.dependency_inventory.exists() or spec.dependency_inventory.is_symlink():
            raise ContractError("DEPENDENCY_INVENTORY_ALREADY_EXISTS_NO_CLOBBER")
        if spec.attempt.exists() or spec.attempt.is_symlink():
            raise ContractError("ATTEMPT_NAMESPACE_NOT_FRESH")
        conflicts = scan_processes(spec)
        if conflicts:
            raise ContractError("CONFLICTING_PROCESS_PRESENT")
        value = {
            "schema_version": DEPENDENCY_SCHEMA,
            "created_at_utc": now_utc(),
            "status": "FROZEN_RESOLVED_ELF_DEPENDENCY_CLOSURE",
            "core": build_dependency_core(spec),
            "claims": {"hfnet_started": False, "model_loaded": False, "retry_authorized": False},
        }
        write_exclusive(spec.dependency_inventory, canonical_json(value))
        written = file_identity(spec.dependency_inventory)
    except (ContractError, OSError, ValueError) as error:
        errors.append(str(error))
    return {
        "schema_version": DEPENDENCY_SCHEMA,
        "status": "DEPENDENCY_INVENTORY_FROZEN" if not errors else "DEPENDENCY_INVENTORY_BLOCKED",
        "ready": not errors,
        "return_code": RC_OK if not errors else RC_BLOCKED,
        "errors": errors,
        "identity": written,
        "claims": {"hfnet_started": False},
    }


def audit_dependencies(spec: Spec) -> Dict[str, Any]:
    value = read_canonical_json(spec.dependency_inventory)
    if not isinstance(value, dict) or value.get("schema_version") != DEPENDENCY_SCHEMA:
        raise ContractError("DEPENDENCY_INVENTORY_SCHEMA_MISMATCH")
    if value.get("status") != "FROZEN_RESOLVED_ELF_DEPENDENCY_CLOSURE":
        raise ContractError("DEPENDENCY_INVENTORY_STATUS_MISMATCH")
    if value.get("claims") != {"hfnet_started": False, "model_loaded": False, "retry_authorized": False}:
        raise ContractError("DEPENDENCY_INVENTORY_CLAIMS_MISMATCH")
    current = build_dependency_core(spec)
    if current != value.get("core"):
        raise ContractError("ELF_DEPENDENCY_CLOSURE_DRIFT")
    return {"inventory": file_identity(spec.dependency_inventory), "core": current}


def _load_input_auditor(path: Path) -> ModuleType:
    source = path.read_bytes()
    module = ModuleType("phase_f_h03_pinned_input_auditor")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def full_tree_identity(root: Path) -> Dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("INPUT_ROOT_MISSING_OR_SYMLINK")
    rows: List[Tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ContractError("INPUT_TREE_SYMLINK:%s" % path)
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError("INPUT_TREE_SPECIAL_FILE:%s" % path)
        digest = hashlib.sha256()
        crc = 0
        size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(block)
                crc = zlib.crc32(block, crc)
                size += len(block)
        rows.append((path.relative_to(root).as_posix(), size, digest.hexdigest(), "%08x" % (crc & 0xFFFFFFFF)))
    tree_digest = hashlib.sha256()
    tree_crc = 0
    for relative, size, digest, crc in rows:
        record = ("%s\0%s\0%s\0%s\n" % (relative, size, digest, crc)).encode("utf-8")
        tree_digest.update(record)
        tree_crc = zlib.crc32(record, tree_crc)
    result = {
        "root": str(absolute(root)),
        "file_count": len(rows),
        "total_bytes": sum(row[1] for row in rows),
        "tree_sha256": tree_digest.hexdigest(),
        "tree_crc32": "%08x" % (tree_crc & 0xFFFFFFFF),
        "record_algorithm": "sorted_utf8_relative_path_NUL_size_NUL_sha256_NUL_crc32_newline",
    }
    for key, expected in EXPECTED_FULL_INPUT.items():
        if result.get(key) != expected:
            raise ContractError("FULL_INPUT_TREE_IDENTITY_MISMATCH:%s" % key)
    return result


def audit_input(spec: Spec) -> Dict[str, Any]:
    require_identity(spec.input_auditor, spec.expected["input_auditor"], "input_auditor")
    module = _load_input_auditor(spec.input_auditor)
    try:
        independent = module.audit(spec.input_root, module.SOURCE_ARCHIVE, spec.config, spec.selector)
    except Exception as error:
        raise ContractError("INDEPENDENT_INPUT_AUDIT_FAILED:%s:%s" % (type(error).__name__, error)) from error
    if independent.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT":
        raise ContractError("INDEPENDENT_INPUT_AUDIT_STATUS_MISMATCH")
    if independent.get("file_count_including_manifest") != CAMERA_COUNT + 4:
        raise ContractError("INDEPENDENT_INPUT_FILE_COUNT_MISMATCH")
    return {"independent": independent, "full_tree": full_tree_identity(spec.input_root)}


def _git_value(spec: Spec, arguments: Sequence[str]) -> str:
    return _command(["git", "-C", str(spec.official_root)] + list(arguments)).strip()


def audit_stack(spec: Spec) -> Dict[str, Any]:
    paths = {
        "passed_stack_lock": spec.passed_stack_lock,
        "selector": spec.selector,
        "materializer": spec.materializer,
        "materializer_test": spec.materializer_test,
        "input_auditor": spec.input_auditor,
        "preparation_audit": spec.preparation_audit,
        "config": spec.config,
        "binary": spec.binary,
        "build_manifest": spec.build_manifest,
        "official_library": spec.official_library,
        "official_entry": spec.official_entry,
        "headless_source": spec.headless_source,
        "onnx": spec.onnx,
        "cache": spec.cache,
    }
    identities = {name: require_identity(path, spec.expected[name], name) for name, path in paths.items()}
    identities["runner_test"] = file_identity(RUNNER_TEST)
    if not os.access(str(spec.binary), os.X_OK):
        raise ContractError("OFFICIAL_ELF_NOT_EXECUTABLE")
    commit = _git_value(spec, ["rev-parse", "HEAD"])
    tree = _git_value(spec, ["rev-parse", "HEAD^{tree}"])
    origin = _git_value(spec, ["remote", "get-url", "origin"])
    if (commit, tree, origin) != (OFFICIAL_COMMIT, OFFICIAL_TREE, OFFICIAL_ORIGIN):
        raise ContractError("OFFICIAL_GIT_IDENTITY_MISMATCH")
    return {
        "identities": identities,
        "official_git": {"commit": commit, "tree": tree, "origin": origin},
        "headless_delta": "official mono_inertial_euroc.cc included directly; constructor viewer flag forced false only",
        "sensor": "IMU_MONOCULAR",
        "track_call": "SLAM.TrackMonocular(im,tframe,vImuMeas)",
    }


def scan_processes(spec: Spec) -> List[Dict[str, object]]:
    conflicts: List[Dict[str, object]] = []
    expected_exe = str(absolute(spec.binary))
    forbidden_comm_tokens = ("hfnet", "vins", "orb_slam", "detector", "evaluator")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        pid = int(entry.name)
        try:
            exe = os.readlink(str(entry / "exe"))
        except OSError:
            exe = ""
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            comm = ""
        lowered = comm.lower()
        if exe == expected_exe or any(token in lowered for token in forbidden_comm_tokens):
            conflicts.append({"pid": pid, "comm": comm, "exact_phase_f_elf": exe == expected_exe})
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def collect_profile(spec: Spec) -> Dict[str, Any]:
    stack = audit_stack(spec)
    return {
        "scientific_role": ROLE,
        "preparation_and_stack": stack,
        "dependencies": audit_dependencies(spec),
        "input": audit_input(spec),
        "selection": {
            "sequence": "AQUALOC harbor_sequence_03",
            "source_frame_indices_inclusive": [1_800, 3_600],
            "camera_count": CAMERA_COUNT,
            "preroll_relative_indices_inclusive": [PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX],
            "score_relative_indices_inclusive": [SCORE_FIRST_INDEX, SCORE_LAST_INDEX],
            "preroll_nominal_seconds": 45,
            "score_nominal_seconds": 45,
        },
    }


def profile_sha256(profile: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(profile)).hexdigest()


def preflight(spec: Spec = DEFAULT_SPEC) -> Dict[str, Any]:
    errors: List[str] = []
    profile = None
    conflicts: List[Dict[str, object]] = []
    try:
        if spec.attempt.exists() or spec.attempt.is_symlink():
            raise ContractError("ATTEMPT_NAMESPACE_NOT_FRESH")
        if spec.execution_lock.exists() or spec.execution_lock.is_symlink():
            raise ContractError("EXECUTION_LOCK_PREEXISTS_BEFORE_PREPARE")
        conflicts = scan_processes(spec)
        if conflicts:
            raise ContractError("CONFLICTING_PROCESS_PRESENT")
        profile = collect_profile(spec)
    except (ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(str(error))
    return {
        "schema_version": PREFLIGHT_SCHEMA,
        "status": "PREFLIGHT_GO_FOR_PREPARE" if not errors else "PREFLIGHT_BLOCKED",
        "ready": not errors,
        "return_code": RC_OK if not errors else RC_BLOCKED,
        "errors": errors,
        "profile": profile,
        "process_conflicts": conflicts,
        "claims": {"filesystem_writes": False, "hfnet_started": False},
    }


def derive_runtime_config(source: str, model_dir: Path) -> str:
    if source.count(BASE_MODEL_PATH_LINE) != 1:
        raise ContractError("BASE_CONFIG_MODEL_PATH_LINE_MISMATCH")
    replacement = 'Extractor.modelPath: "%s/"' % absolute(model_dir)
    derived = source.replace(BASE_MODEL_PATH_LINE, replacement)
    before = source.splitlines(keepends=True)
    after = derived.splitlines(keepends=True)
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if len(before) != len(after) or len(changed) != 1:
        raise ContractError("RUNTIME_CONFIG_NOT_EXACTLY_ONE_LINE_CHANGE")
    required = (
        'Camera.type: "KannalaBrandt8"', "Camera.width: 640", "Camera.height: 512",
        "IMU.NoiseGyro: 0.001", "IMU.NoiseAcc: 0.02", "IMU.GyroWalk: 0.00005",
        "IMU.AccWalk: 0.001", "IMU.Frequency: 200.0", 'Extractor.type: "HFNetRT"',
        "Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4", "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01", "loopClosing: 1",
    )
    if any(source.count(token) != 1 or derived.count(token) != 1 for token in required):
        raise ContractError("RUNTIME_CONFIG_FROZEN_TOKEN_DRIFT")
    return derived


def _prepared_allowed() -> set:
    return {
        "prepared_manifest.json",
        "runtime_config_model_path_only.yaml",
        "run_local_model/HFNet-RT/HF-Net.onnx",
        "run_local_model/HFNet-RT/HF-Net.cache",
    }


def _attempt_files(spec: Spec) -> set:
    observed = set()
    for path in spec.attempt.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ContractError("ATTEMPT_SYMLINK_FORBIDDEN:%s" % path)
        if stat.S_ISREG(metadata.st_mode):
            observed.add(path.relative_to(spec.attempt).as_posix())
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ContractError("ATTEMPT_SPECIAL_FILE_FORBIDDEN:%s" % path)
    return observed


def _launch_contract(spec: Spec) -> Dict[str, Any]:
    return {
        "argv": command_argv(spec),
        "environment": runtime_environment(spec),
        "cwd": str(absolute(spec.attempt)),
        "timeout_seconds": spec.timeout_seconds,
        "authorization_token": AUTHORIZATION_TOKEN,
        "maximum_elf_starts": 1,
        "maximum_popen_invocations": 1,
        "retry": False,
    }


def prepare(spec: Spec = DEFAULT_SPEC) -> Dict[str, Any]:
    decision = preflight(spec)
    if not decision["ready"]:
        decision.update({"status": "PREPARE_BLOCKED", "return_code": RC_BLOCKED})
        return decision
    temporary: Optional[Path] = None
    try:
        parent = spec.attempt.parent
        parent.mkdir(parents=True, exist_ok=True)
        if spec.attempt.exists() or spec.attempt.is_symlink():
            raise ContractError("ATTEMPT_NAMESPACE_RACE_OR_CLOBBER")
        temporary = Path(tempfile.mkdtemp(prefix=".%s.prepare." % spec.attempt.name, dir=str(parent)))
        temp_model = temporary / "run_local_model/HFNet-RT"
        temp_model.mkdir(parents=True)
        temp_onnx = temp_model / "HF-Net.onnx"
        temp_cache = temp_model / "HF-Net.cache"
        shutil.copyfile(str(spec.onnx), str(temp_onnx))
        shutil.copyfile(str(spec.cache), str(temp_cache))
        os.chmod(str(temp_onnx), 0o444)
        os.chmod(str(temp_cache), 0o644)
        local_onnx = file_identity(temp_onnx, recorded_path=spec.local_onnx)
        local_cache = file_identity(temp_cache, recorded_path=spec.local_cache)
        if content_identity(temp_onnx) != content_identity(spec.onnx):
            raise ContractError("RUN_LOCAL_ONNX_COPY_MISMATCH")
        if content_identity(temp_cache) != content_identity(spec.cache):
            raise ContractError("RUN_LOCAL_CACHE_COPY_MISMATCH")
        config_bytes = derive_runtime_config(spec.config.read_text(encoding="utf-8"), spec.model_dir).encode("utf-8")
        temp_config = temporary / spec.runtime_config.name
        write_exclusive(temp_config, config_bytes)
        runtime_config = file_identity(temp_config, recorded_path=spec.runtime_config)
        manifest = {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_UNSTARTED_FRESH_ATTEMPT_001",
            "scientific_role": ROLE,
            "prepared_at_utc": now_utc(),
            "namespace": str(absolute(spec.attempt)),
            "frozen_profile": decision["profile"],
            "frozen_profile_sha256": profile_sha256(decision["profile"]),
            "run_local": {"onnx": local_onnx, "cache_seed": local_cache, "runtime_config": runtime_config},
            "shared_cache_preparation_identity": file_identity(spec.cache),
            "launch": _launch_contract(spec),
            "policy": {"one_shot": True, "retry": False, "result_conditioned_selection": False},
            "claims": {"hfnet_started": False, "trajectory_observed": False, "superiority_claimed": False},
        }
        write_exclusive(temporary / spec.prepared_manifest.name, canonical_json(manifest))
        fsync_dir(temp_model)
        fsync_dir(temp_model.parent)
        fsync_dir(temporary)
        if file_identity(spec.cache) != manifest["shared_cache_preparation_identity"]:
            raise ContractError("SHARED_CACHE_CHANGED_DURING_PREPARE")
        os.rename(str(temporary), str(spec.attempt))
        temporary = None
        fsync_dir(parent)
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_UNSTARTED_FRESH_ATTEMPT_001",
            "ready_for_lock": True,
            "return_code": RC_OK,
            "prepared_manifest": file_identity(spec.prepared_manifest),
            "claims": {"hfnet_started": False},
        }
    except (ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        if temporary is not None and temporary.exists():
            shutil.rmtree(str(temporary))
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARE_BLOCKED",
            "ready_for_lock": False,
            "return_code": RC_BLOCKED,
            "errors": [str(error)],
            "claims": {"hfnet_started": False},
        }


def audit_prepared(spec: Spec, *, require_lock: bool) -> Dict[str, Any]:
    if spec.attempt.is_symlink() or not spec.attempt.is_dir():
        raise ContractError("PREPARED_NAMESPACE_MISSING_OR_SYMLINK")
    manifest = read_canonical_json(spec.prepared_manifest)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PREPARED_SCHEMA:
        raise ContractError("PREPARED_MANIFEST_SCHEMA_MISMATCH")
    profile = collect_profile(spec)
    if manifest.get("frozen_profile") != profile or manifest.get("frozen_profile_sha256") != profile_sha256(profile):
        raise ContractError("PREPARED_FROZEN_PROFILE_DRIFT")
    local_onnx = file_identity(spec.local_onnx)
    local_cache = file_identity(spec.local_cache)
    runtime_config = file_identity(spec.runtime_config)
    expected_runtime = derive_runtime_config(spec.config.read_text(encoding="utf-8"), spec.model_dir).encode("utf-8")
    if spec.runtime_config.read_bytes() != expected_runtime:
        raise ContractError("RUNTIME_CONFIG_CONTENT_DRIFT")
    if manifest.get("run_local") != {"onnx": local_onnx, "cache_seed": local_cache, "runtime_config": runtime_config}:
        raise ContractError("RUN_LOCAL_IDENTITY_DRIFT")
    if content_identity(spec.local_onnx) != content_identity(spec.onnx):
        raise ContractError("RUN_LOCAL_ONNX_NOT_SHARED_COPY")
    if content_identity(spec.local_cache) != content_identity(spec.cache):
        raise ContractError("RUN_LOCAL_CACHE_NOT_SEED_COPY")
    if manifest.get("shared_cache_preparation_identity") != file_identity(spec.cache):
        raise ContractError("SHARED_CACHE_PREPARATION_DRIFT")
    if manifest.get("launch") != _launch_contract(spec):
        raise ContractError("PREPARED_LAUNCH_CONTRACT_DRIFT")
    files = _attempt_files(spec)
    if files != _prepared_allowed():
        raise ContractError("PRESTART_ATTEMPT_FILE_SET_DRIFT:%s" % sorted(files))
    for path in (spec.start_claim, spec.stdout_log, spec.stderr_log, spec.result_dir, spec.run_result):
        if path.exists() or path.is_symlink():
            raise ContractError("PRESTART_OUTPUT_ALREADY_EXISTS:%s" % path.name)
    result = {
        "manifest": manifest,
        "prepared_manifest": file_identity(spec.prepared_manifest),
        "profile": profile,
        "run_local": {"onnx": local_onnx, "cache_seed": local_cache, "runtime_config": runtime_config},
    }
    if require_lock:
        result["execution_lock"] = audit_execution_lock(spec, result)
    return result


def build_execution_lock(spec: Spec, prepared: Mapping[str, Any], locked_at: str) -> Dict[str, Any]:
    profile = prepared["profile"]
    stack = profile["preparation_and_stack"]["identities"]
    return {
        "schema_version": LOCK_SCHEMA,
        "status": "LOCKED_PRESTART_EXACTLY_ONE_HFNET_ELF_START",
        "locked_at_utc": locked_at,
        "scientific_role": ROLE,
        "runner": file_identity(Path(__file__).resolve()),
        "prepared_manifest": prepared["prepared_manifest"],
        "frozen_profile_sha256": profile_sha256(profile),
        "dependency_inventory": file_identity(spec.dependency_inventory),
        "passed_stack_lock": stack["passed_stack_lock"],
        "selector": stack["selector"],
        "materializer": stack["materializer"],
        "input_auditor": stack["input_auditor"],
        "runner_test": stack["runner_test"],
        "preparation_audit": stack["preparation_audit"],
        "config": stack["config"],
        "official_elf": stack["binary"],
        "official_library": stack["official_library"],
        "official_entry": stack["official_entry"],
        "headless_source": stack["headless_source"],
        "resolved_dependencies": {
            "count": profile["dependencies"]["core"]["dependency_count"],
            "total_bytes": profile["dependencies"]["core"]["dependency_total_bytes"],
            "records_sha256": profile["dependencies"]["core"]["dependency_records_sha256"],
        },
        "shared_model": stack["onnx"],
        "shared_cache_seed": stack["cache"],
        "run_local": prepared["run_local"],
        "full_input_tree": profile["input"]["full_tree"],
        "launch": _launch_contract(spec),
        "attempt": {
            "path": str(absolute(spec.attempt)),
            "process_start_claim_absent": True,
            "run_result_absent": True,
            "maximum_elf_starts": 1,
            "retry": False,
        },
        "selection": profile["selection"],
        "exploratory_usability_gate": {
            "raw_returncode_zero": True,
            "timed_out": False,
            "synchronously_reaped": True,
            "minimum_last_camera_index": MIN_LAST_CAMERA_INDEX,
            "minimum_score_poses": MIN_SCORE_POSES,
            "minimum_contiguous_score_poses": MIN_CONTIGUOUS_SCORE_POSES,
            "minimum_score_keyframes": MIN_SCORE_KEYFRAMES,
        },
        "claim_boundary": {
            "exploratory_underwater_usability_only": True,
            "accuracy_claimed": False,
            "superiority_claimed": False,
            "comparison_to_other_learning_system_claimed": False,
        },
    }


def lock_execution(spec: Spec = DEFAULT_SPEC) -> Dict[str, Any]:
    try:
        if spec.execution_lock.exists() or spec.execution_lock.is_symlink():
            raise ContractError("EXECUTION_LOCK_ALREADY_EXISTS_NO_CLOBBER")
        prepared = audit_prepared(spec, require_lock=False)
        conflicts = scan_processes(spec)
        if conflicts:
            raise ContractError("CONFLICTING_PROCESS_PRESENT")
        value = build_execution_lock(spec, prepared, now_utc())
        write_exclusive(spec.execution_lock, canonical_json(value))
        return {
            "schema_version": LOCK_SCHEMA,
            "status": "EXECUTION_LOCK_FROZEN",
            "ready_for_check": True,
            "return_code": RC_OK,
            "identity": file_identity(spec.execution_lock),
            "claims": {"hfnet_started": False},
        }
    except (ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        return {
            "schema_version": LOCK_SCHEMA,
            "status": "EXECUTION_LOCK_BLOCKED",
            "ready_for_check": False,
            "return_code": RC_BLOCKED,
            "errors": [str(error)],
            "claims": {"hfnet_started": False},
        }


def audit_execution_lock(spec: Spec, prepared: Mapping[str, Any]) -> Dict[str, Any]:
    value = read_canonical_json(spec.execution_lock)
    if not isinstance(value, dict) or not isinstance(value.get("locked_at_utc"), str):
        raise ContractError("EXECUTION_LOCK_STRUCTURE_INVALID")
    expected = build_execution_lock(spec, prepared, value["locked_at_utc"])
    if value != expected:
        raise ContractError("EXECUTION_LOCK_SEMANTICS_OR_PIN_DRIFT")
    return {"identity": file_identity(spec.execution_lock), "value": value}


def check(spec: Spec = DEFAULT_SPEC) -> Dict[str, Any]:
    errors: List[str] = []
    audit = None
    conflicts: List[Dict[str, object]] = []
    try:
        audit = audit_prepared(spec, require_lock=True)
        conflicts = scan_processes(spec)
        if conflicts:
            raise ContractError("CONFLICTING_PROCESS_PRESENT")
    except (ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(str(error))
    return {
        "schema_version": CHECK_SCHEMA,
        "status": "PRESTART_GO_EXACTLY_ONE_ELF_START" if not errors else "PRESTART_BLOCKED",
        "ready": not errors,
        "return_code": RC_OK if not errors else RC_BLOCKED,
        "errors": errors,
        "audit": audit,
        "process_conflicts": conflicts,
        "authorization_token": AUTHORIZATION_TOKEN,
        "claims": {"filesystem_writes": False, "hfnet_started": False},
    }


def parse_camera_timestamps(path: Path) -> List[int]:
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ContractError("CAMERA_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in raw.decode("ascii").splitlines()]
    except ValueError as error:
        raise ContractError("CAMERA_TIMES_INVALID") from error
    if len(stamps) != CAMERA_COUNT or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("CAMERA_TIMES_COUNT_OR_ORDER_MISMATCH")
    return stamps


def _contiguous_metrics(indices: Sequence[int], lower: int, upper: int) -> Dict[str, Any]:
    selected = [index for index in indices if lower <= index <= upper]
    runs: List[List[int]] = []
    for index in selected:
        if not runs or index != runs[-1][-1] + 1:
            runs.append([index])
        else:
            runs[-1].append(index)
    gaps = []
    for left, right in zip(selected, selected[1:]):
        if right > left + 1:
            gaps.append({"after": left, "before": right, "missing_count": right - left - 1})
    return {
        "count": len(selected),
        "coverage_fraction": len(selected) / float(upper - lower + 1),
        "first_index": selected[0] if selected else None,
        "last_index": selected[-1] if selected else None,
        "contiguous_run_count": len(runs),
        "longest_contiguous_run": max((len(run) for run in runs), default=0),
        "gap_count": len(gaps),
        "gaps": gaps[:100],
        "gaps_truncated": len(gaps) > 100,
    }


def parse_trajectory(path: Path, camera_ns: Sequence[int], *, keyframes: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "exists": False, "identity": None, "pose_count": 0, "valid": False,
        "strictly_increasing_timestamps": False, "unique_strict_camera_associations": False,
        "association_max_abs_error_ns": None, "all_quaternions_within_tolerance": False,
        "preroll": _contiguous_metrics([], PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX),
        "score": _contiguous_metrics([], SCORE_FIRST_INDEX, SCORE_LAST_INDEX),
        "overall": _contiguous_metrics([], 0, CAMERA_COUNT - 1), "errors": [],
    }
    try:
        if path.is_symlink() or not path.is_file():
            raise ContractError("TRAJECTORY_MISSING_OR_NOT_REGULAR")
        raw = path.read_bytes()
        result["exists"] = True
        result["identity"] = file_identity(path)
        lines = raw.decode("ascii").splitlines()
    except (ContractError, OSError, UnicodeError) as error:
        result["errors"] = [str(error)]
        return result
    if not lines or any(not line.strip() for line in lines):
        result["errors"] = ["TRAJECTORY_EMPTY_OR_BLANK_ROW"]
        return result
    stamps: List[int] = []
    errors: List[str] = []
    for row_index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            errors.append("ROW_%d_FIELD_COUNT" % row_index)
            continue
        try:
            stamp_value = Decimal(fields[0])
            values = [float(field) for field in fields[1:]]
        except (InvalidOperation, ValueError):
            errors.append("ROW_%d_NUMERIC" % row_index)
            continue
        if not stamp_value.is_finite() or stamp_value != stamp_value.to_integral_value() or not all(math.isfinite(v) for v in values):
            errors.append("ROW_%d_NONFINITE_OR_NONINTEGER_TIMESTAMP" % row_index)
            continue
        norm = math.sqrt(sum(value * value for value in values[3:7]))
        if abs(norm - 1.0) > QUATERNION_NORM_TOLERANCE:
            errors.append("ROW_%d_QUATERNION_NORM" % row_index)
            continue
        stamps.append(int(stamp_value))
    strict = not errors and all(right > left for left, right in zip(stamps, stamps[1:]))
    indices: List[int] = []
    association_errors: List[int] = []
    if not errors:
        for row_index, stamp in enumerate(stamps):
            insertion = bisect.bisect_left(camera_ns, stamp)
            candidates = [i for i in (insertion - 1, insertion) if 0 <= i < len(camera_ns)]
            if not candidates:
                errors.append("ROW_%d_NO_CAMERA_ASSOCIATION" % row_index)
                break
            index = min(candidates, key=lambda i: (abs(camera_ns[i] - stamp), i))
            delta = abs(camera_ns[index] - stamp)
            if delta > MAX_ASSOCIATION_ERROR_NS:
                errors.append("ROW_%d_CAMERA_ASSOCIATION_GT_%dns" % (row_index, MAX_ASSOCIATION_ERROR_NS))
                break
            indices.append(index)
            association_errors.append(delta)
    associations_valid = (
        not errors and len(indices) == len(stamps) and len(set(indices)) == len(indices)
        and all(right > left for left, right in zip(indices, indices[1:]))
    )
    if indices and not associations_valid and not errors:
        errors.append("CAMERA_ASSOCIATIONS_NOT_UNIQUE_STRICT")
    result.update({
        "pose_count": len(stamps),
        "valid": not errors and strict and associations_valid,
        "strictly_increasing_timestamps": strict,
        "unique_strict_camera_associations": associations_valid,
        "association_max_abs_error_ns": max(association_errors) if association_errors else None,
        "all_quaternions_within_tolerance": not any("QUATERNION" in error for error in errors),
        "preroll": _contiguous_metrics(indices, PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX),
        "score": _contiguous_metrics(indices, SCORE_FIRST_INDEX, SCORE_LAST_INDEX),
        "overall": _contiguous_metrics(indices, 0, CAMERA_COUNT - 1),
        "errors": errors[:100],
        "errors_truncated": len(errors) > 100,
        "kind": "keyframes" if keyframes else "frame_trajectory",
    })
    return result


def summarize_warnings(path: Path) -> Dict[str, Any]:
    patterns = {
        "warning": re.compile(r"warning", re.I), "error": re.compile(r"error", re.I),
        "failed": re.compile(r"fail(?:ed|ure)?", re.I), "lost": re.compile(r"\blost\b", re.I),
        "reset": re.compile(r"reset", re.I), "not_initialized": re.compile(r"not initialized", re.I),
        "not_enough_acceleration": re.compile(r"not enough acceleration", re.I),
        "cuda": re.compile(r"cuda", re.I), "tensorrt": re.compile(r"tensor\s*rt|tensorrt", re.I),
        "segfault": re.compile(r"segmentation fault|segfault", re.I),
        "terminate": re.compile(r"terminate called|aborted", re.I),
    }
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return {"read_error": str(error), "line_count": None, "patterns": {}}
    result = {}
    for label, pattern in patterns.items():
        matches = [line[:500] for line in lines if pattern.search(line)]
        result[label] = {"count": len(matches), "examples": matches[:10], "examples_truncated": len(matches) > 10}
    return {"line_count": len(lines), "patterns": result}


def result_tree_identity(root: Path) -> Dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        return {"exists": False, "files": [], "file_count": 0, "total_bytes": 0, "tree_sha256": None}
    records = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ContractError("RESULT_SYMLINK_FORBIDDEN:%s" % path)
        if path.is_file():
            observed = file_identity(path)
            observed["path"] = path.relative_to(root).as_posix()
            records.append(observed)
        elif not path.is_dir():
            raise ContractError("RESULT_SPECIAL_FILE_FORBIDDEN:%s" % path)
    return {
        "exists": True, "files": records, "file_count": len(records),
        "total_bytes": sum(int(row["size_bytes"]) for row in records),
        "tree_sha256": hashlib.sha256(canonical_json(records)).hexdigest(),
    }


def launch_once(spec: Spec) -> Execution:
    started = time.monotonic()
    stdout_fd = os.open(str(spec.stdout_log), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stderr_fd = os.open(str(spec.stderr_log), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    process = None
    signals: List[str] = []
    try:
        spec.result_dir.mkdir(parents=False, exist_ok=False)
        with os.fdopen(stdout_fd, "wb", closefd=False) as stdout_stream, os.fdopen(stderr_fd, "wb", closefd=False) as stderr_stream:
            try:
                process = subprocess.Popen(
                    command_argv(spec), cwd=str(spec.attempt), env=runtime_environment(spec),
                    stdin=subprocess.DEVNULL, stdout=stdout_stream, stderr=stderr_stream,
                    start_new_session=True,
                )
            except OSError as error:
                stderr_stream.write(("Popen failed: %s:%s\n" % (type(error).__name__, error)).encode("utf-8", errors="replace"))
                stderr_stream.flush()
                os.fsync(stderr_stream.fileno())
                return Execution(1, False, None, None, False, True, time.monotonic() - started, error="%s:%s" % (type(error).__name__, error))
            timed_out = False
            try:
                returncode = process.wait(timeout=spec.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    signals.append("SIGTERM")
                except ProcessLookupError:
                    pass
                try:
                    returncode = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        signals.append("SIGKILL")
                    except ProcessLookupError:
                        pass
                    returncode = process.wait()
            stdout_stream.flush()
            stderr_stream.flush()
            os.fsync(stdout_stream.fileno())
            os.fsync(stderr_stream.fileno())
            return Execution(1, True, process.pid, returncode, timed_out, process.poll() is not None, time.monotonic() - started, tuple(signals))
    finally:
        os.close(stdout_fd)
        os.close(stderr_fd)
        if spec.stdout_log.exists():
            os.chmod(str(spec.stdout_log), 0o444)
        if spec.stderr_log.exists():
            os.chmod(str(spec.stderr_log), 0o444)


def build_start_claim(spec: Spec, prepared: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": CLAIM_SCHEMA,
        "status": "O_EXCL_CLAIM_BEFORE_ONLY_POPEN_INVOCATION",
        "claimed_at_utc": now_utc(),
        "scientific_role": ROLE,
        "runner": file_identity(Path(__file__).resolve()),
        "execution_lock": prepared["execution_lock"]["identity"],
        "prepared_manifest": prepared["prepared_manifest"],
        "frozen_profile_sha256": profile_sha256(prepared["profile"]),
        "launch": _launch_contract(spec),
        "popen_invocations_claimed": 1,
        "maximum_elf_starts": 1,
        "retry": False,
    }


def run(spec: Spec = DEFAULT_SPEC, *, authorization_token: str = "") -> Dict[str, Any]:
    if authorization_token != AUTHORIZATION_TOKEN:
        return {
            "schema_version": RESULT_SCHEMA, "status": "RUN_NOT_AUTHORIZED", "return_code": RC_BLOCKED,
            "errors": ["EXACT_ONE_SHOT_AUTHORIZATION_TOKEN_REQUIRED"],
            "execution": {"popen_invocations": 0, "process_started": False, "retry": False},
        }
    try:
        checked = check(spec)
        if not checked["ready"]:
            raise ContractError("PRESTART_CHECK_NOT_GO:%s" % checked["errors"])
        prepared = checked["audit"]
        profile_pre = prepared["profile"]
        local_pre = {
            "onnx": file_identity(spec.local_onnx), "cache": file_identity(spec.local_cache),
            "runtime_config": file_identity(spec.runtime_config), "shared_cache": file_identity(spec.cache),
        }
        claim = build_start_claim(spec, prepared)
        write_exclusive(spec.start_claim, canonical_json(claim))
        claim_identity = file_identity(spec.start_claim)
    except (ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        return {
            "schema_version": RESULT_SCHEMA, "status": "RUN_CONTRACT_BLOCKED", "return_code": RC_BLOCKED,
            "errors": [str(error)],
            "execution": {"popen_invocations": 0, "process_started": False, "retry": False},
        }

    started_at = now_utc()
    try:
        execution = launch_once(spec)
    except Exception as error:
        execution = Execution(1, False, None, None, False, True, 0.0, error="LAUNCH_SUPERVISOR_EXCEPTION:%s:%s" % (type(error).__name__, error))
    ended_at = now_utc()

    post_errors: List[str] = []
    try:
        profile_post = collect_profile(spec)
    except Exception as error:
        profile_post = None
        post_errors.append("POST_FULL_PROFILE_FAILED:%s:%s" % (type(error).__name__, error))

    def safe_identity(path: Path, label: str) -> Optional[Dict[str, object]]:
        try:
            return file_identity(path)
        except Exception as error:
            post_errors.append("POST_IDENTITY_FAILED:%s:%s" % (label, error))
            return None

    local_post = {
        "onnx": safe_identity(spec.local_onnx, "local_onnx"),
        "cache": safe_identity(spec.local_cache, "local_cache"),
        "runtime_config": safe_identity(spec.runtime_config, "runtime_config"),
        "shared_cache": safe_identity(spec.cache, "shared_cache"),
    }
    try:
        camera_ns = parse_camera_timestamps(spec.input_root / "cam0_times.txt")
    except Exception as error:
        camera_ns = []
        post_errors.append("CAMERA_TIMESTAMPS_POST_PARSE_FAILED:%s" % error)
    trajectory = parse_trajectory(spec.result_dir / "trajectory.txt", camera_ns, keyframes=False) if camera_ns else {"valid": False, "errors": ["NO_CAMERA_GRID"]}
    keyframes = parse_trajectory(spec.result_dir / "trajectory_keyframe.txt", camera_ns, keyframes=True) if camera_ns else {"valid": False, "errors": ["NO_CAMERA_GRID"]}
    try:
        result_tree = result_tree_identity(spec.result_dir)
    except Exception as error:
        result_tree = None
        post_errors.append("RESULT_TREE_AUDIT_FAILED:%s" % error)
    stdout_identity = safe_identity(spec.stdout_log, "stdout")
    stderr_identity = safe_identity(spec.stderr_log, "stderr")
    warnings = {
        "stdout": summarize_warnings(spec.stdout_log),
        "stderr": summarize_warnings(spec.stderr_log),
    }
    profile_unchanged = profile_post == profile_pre
    immutable_local_exact = local_post["onnx"] == local_pre["onnx"] and local_post["runtime_config"] == local_pre["runtime_config"]
    shared_cache_exact = local_post["shared_cache"] == local_pre["shared_cache"]
    trajectory_gate = bool(
        trajectory.get("valid")
        and trajectory.get("overall", {}).get("last_index") is not None
        and trajectory["overall"]["last_index"] >= MIN_LAST_CAMERA_INDEX
        and trajectory.get("score", {}).get("count", 0) >= MIN_SCORE_POSES
        and trajectory.get("score", {}).get("longest_contiguous_run", 0) >= MIN_CONTIGUOUS_SCORE_POSES
    )
    keyframe_gate = bool(keyframes.get("valid") and keyframes.get("score", {}).get("count", 0) >= MIN_SCORE_KEYFRAMES)
    execution_gate = bool(
        execution.popen_invocations == 1 and execution.process_started and execution.returncode == 0
        and not execution.timed_out and execution.synchronously_reaped
    )
    usability_pass = bool(
        execution_gate and trajectory_gate and keyframe_gate and profile_unchanged
        and immutable_local_exact and shared_cache_exact and not post_errors
    )
    errors = list(post_errors)
    if not execution_gate:
        errors.append("EXECUTION_GATE_FAILED")
    if not trajectory_gate:
        errors.append("FRAME_TRAJECTORY_USABILITY_GATE_FAILED")
    if not keyframe_gate:
        errors.append("KEYFRAME_SCORE_SUPPORT_GATE_FAILED")
    if not profile_unchanged:
        errors.append("FULL_FROZEN_PROFILE_PRE_POST_MISMATCH")
    if not immutable_local_exact:
        errors.append("RUN_LOCAL_ONNX_OR_CONFIG_CHANGED")
    if not shared_cache_exact:
        errors.append("SHARED_CACHE_CHANGED")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": "PASS_EXPLORATORY_UNDERWATER_USABILITY" if usability_pass else "FAIL_EXPLORATORY_UNDERWATER_USABILITY",
        "return_code": RC_OK if usability_pass else RC_FAILED,
        "scientific_role": ROLE,
        "errors": errors,
        "execution": {
            "popen_invocations": execution.popen_invocations,
            "process_started": execution.process_started,
            "pid": execution.pid,
            "raw_returncode": execution.returncode,
            "timed_out": execution.timed_out,
            "timeout_seconds": spec.timeout_seconds,
            "synchronously_reaped": execution.synchronously_reaped,
            "duration_seconds": execution.duration_seconds,
            "termination_signals": list(execution.termination_signals),
            "supervisor_error": execution.error,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "retry_performed": False,
            "retry_permitted": False,
            "inferred_images_consumed": CAMERA_COUNT if execution.returncode == 0 and not execution.timed_out else None,
            "inference_basis": "official entry returned after its sequential 1801-image loop",
        },
        "pins": {
            "runner": file_identity(Path(__file__).resolve()),
            "execution_lock": prepared["execution_lock"]["identity"],
            "prepared_manifest": prepared["prepared_manifest"],
            "process_start_claim": claim_identity,
            "stdout": stdout_identity,
            "stderr": stderr_identity,
            "run_local_pre": local_pre,
            "run_local_post": local_post,
            "run_local_cache_mutation_recorded_not_assumed_immutable": local_pre["cache"] != local_post["cache"],
        },
        "pre_post": {
            "full_profile_pre_sha256": profile_sha256(profile_pre),
            "full_profile_post_sha256": profile_sha256(profile_post) if profile_post is not None else None,
            "full_profile_exact": profile_unchanged,
            "input_full_tree_pre": profile_pre["input"]["full_tree"],
            "input_full_tree_post": profile_post["input"]["full_tree"] if profile_post is not None else None,
            "resolved_dependencies_pre": profile_pre["dependencies"]["core"],
            "resolved_dependencies_post": profile_post["dependencies"]["core"] if profile_post is not None else None,
            "post_audit_errors": post_errors,
        },
        "support": {
            "frozen_windows": profile_pre["selection"],
            "trajectory": trajectory,
            "keyframes": keyframes,
            "result_tree": result_tree,
            "warnings": warnings,
        },
        "gate": {
            "execution": execution_gate,
            "trajectory_score_continuity": trajectory_gate,
            "keyframe_score_support": keyframe_gate,
            "full_pre_post_profile_exact": profile_unchanged,
            "run_local_onnx_and_config_exact": immutable_local_exact,
            "shared_cache_exact": shared_cache_exact,
            "exploratory_underwater_usability": usability_pass,
        },
        "claim_boundary": {
            "exploratory_underwater_usability_only": True,
            "accuracy_evaluated": False,
            "ground_truth_evaluator_started": False,
            "other_learning_system_compared": False,
            "superiority_claimed": False,
            "formal_paper_claim_authorized": False,
        },
        "sealing_contract": {
            "target": str(absolute(spec.run_result)),
            "write_mode": "O_EXCL_then_fsync_then_chmod_0444",
            "terminal_after_any_started_attempt": True,
            "retry_after_pass_or_fail": False,
        },
    }
    try:
        write_exclusive(spec.run_result, canonical_json(result))
        result["run_result"] = file_identity(spec.run_result)
        result["sealed"] = True
    except Exception as error:
        result["sealed"] = False
        result["errors"].append("RUN_RESULT_SEAL_FAILED:%s:%s" % (type(error).__name__, error))
        result["return_code"] = RC_FAILED
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("snapshot-deps", "preflight", "prepare", "lock", "check", "run"), default="preflight")
    value.add_argument("--attempt", type=Path, default=ATTEMPT)
    value.add_argument("--authorization-token", default="")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    spec = replace(DEFAULT_SPEC, attempt=args.attempt)
    if args.action == "snapshot-deps":
        decision = snapshot_dependencies(spec)
    elif args.action == "preflight":
        decision = preflight(spec)
    elif args.action == "prepare":
        decision = prepare(spec)
    elif args.action == "lock":
        decision = lock_execution(spec)
    elif args.action == "check":
        decision = check(spec)
    else:
        decision = run(spec, authorization_token=args.authorization_token)
    sys.stdout.buffer.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
