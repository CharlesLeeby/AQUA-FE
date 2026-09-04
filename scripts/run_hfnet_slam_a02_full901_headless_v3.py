#!/usr/bin/env python3
"""Fail-closed HFNet-SLAM A02 full901 headless supervisor (revision 3).

The project-side ELF directly links the frozen official c354 library and
includes the frozen official ``mono_inertial_euroc.cc`` control flow.  Its
only semantic delta is ``System(..., bUseViewer=false)``.  The official model,
SLAM sources, settings, thresholds, and algorithms remain unchanged.

``preflight`` is read-only. ``freeze`` writes only a no-clobber contract.
``run`` is the sole action that can start the headless entry, at most once.
This module is safe to import in tests and never starts work on import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from scripts import run_hfnet_slam_a02_full901_diagnostic_v2 as prior

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "aqua-fe-hfnet-slam-a02-full901-headless-contract-v3"
PROFILE_SCHEMA = "aqua-fe-hfnet-slam-a02-full901-headless-profile-v3"
RESULT_SCHEMA = "aqua-fe-hfnet-slam-a02-full901-headless-result-v3"
ROLE = "POST_STOP_HEADLESS_INFRASTRUCTURE_REPAIR_NOT_PREFIX_R1_REPLACEMENT"
COMMIT = prior.EXECUTION_COMMIT
TREE = prior.EXECUTION_TREE
ORIGIN = prior.OFFICIAL_REPOSITORY
RC_OK, RC_FAILED, RC_BLOCKED = 0, 1, 2

DEFAULT_OFFICIAL_ROOT = prior.DEFAULT_OFFICIAL_ROOT
DEFAULT_BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
DEFAULT_BUILD_MANIFEST = DEFAULT_BINARY.parent / "build_manifest.json"
DEFAULT_LIBRARY = DEFAULT_OFFICIAL_ROOT / "lib/libHFNet_SLAM.so"
DEFAULT_ENTRY_SOURCE = DEFAULT_OFFICIAL_ROOT / "Examples/Monocular-Inertial/mono_inertial_euroc.cc"
DEFAULT_HARNESS_SOURCE = ROOT / "scripts/harnesses/hfnet_slam_mono_inertial_euroc_headless_v3.cc"
DEFAULT_CONFIG = prior.DEFAULT_CONFIG
DEFAULT_MODEL_DIR = prior.DEFAULT_MODEL_DIRECTORY
DEFAULT_ONNX = DEFAULT_MODEL_DIR / "HF-Net.onnx"
DEFAULT_CACHE_SEED = DEFAULT_MODEL_DIR / "HF-Net.cache"
DEFAULT_SEQUENCE = prior.DEFAULT_SEQUENCE_ROOT
DEFAULT_RESULT = ROOT / "logs/published_hfnet_slam_v3/post_stop_full901_headless/runs/aqualoc_a02_0005_full901_headless_r3"
DEFAULT_EVIDENCE = ROOT / "logs/published_hfnet_slam_v3/post_stop_full901_headless/drivers/aqualoc_a02_0005_full901_headless_r3"
DEFAULT_CONTRACT = ROOT / "papers/hfnet_slam_a02_full901_headless_run_contract_r3.json"

EXPECTED: Mapping[str, Mapping[str, object]] = {
    "binary": {"sha256": "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb", "size_bytes": 118280},
    "build_manifest": {"sha256": "dc01d34652afbeb9dfd8b64e96b7d3ecdd8a09522796b73207a05e295ca4f8e9", "size_bytes": 1748},
    "official_library": {"sha256": "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717", "size_bytes": 4807712},
    "config": {"sha256": "7e6482653e55b2fcf86a9e5418fd87747677a88eb9c06443d505cda311b80569", "size_bytes": 1807},
    "onnx": {"sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5", "size_bytes": 132238602},
    "cache_seed": {"sha256": "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7", "size_bytes": 853319},
    "official_entry": {"sha256": "fa3effb0c2b99bc4dd83abda443180cf2f017f61710e02fa6b3f9278cc774d39", "size_bytes": 10201},
    "headless_source": {"sha256": "303947840bdc5377656554560c6785b3218a52e034862a63d5d6da0036b81d90", "size_bytes": 1112},
}


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass(frozen=True)
class Spec:
    official_root: Path = DEFAULT_OFFICIAL_ROOT
    binary: Path = DEFAULT_BINARY
    build_manifest: Path = DEFAULT_BUILD_MANIFEST
    official_library: Path = DEFAULT_LIBRARY
    official_entry: Path = DEFAULT_ENTRY_SOURCE
    headless_source: Path = DEFAULT_HARNESS_SOURCE
    config: Path = DEFAULT_CONFIG
    onnx: Path = DEFAULT_ONNX
    cache_seed: Path = DEFAULT_CACHE_SEED
    sequence: Path = DEFAULT_SEQUENCE
    result: Path = DEFAULT_RESULT
    evidence: Path = DEFAULT_EVIDENCE
    contract: Path = DEFAULT_CONTRACT
    expected: Mapping[str, Mapping[str, object]] = field(default_factory=lambda: EXPECTED)
    timeout_seconds: int = prior.TIMEOUT_SECONDS


DEFAULT_SPEC = Spec()
Probe = Callable[[Sequence[str], Optional[Mapping[str, str]], Optional[Path]], CommandResult]
Execute = Callable[[Sequence[str], Mapping[str, str], Optional[Path], int], CommandResult]


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    path = absolute(path)
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    os.chmod(path, mode)


def default_probe(command: Sequence[str], environment: Optional[Mapping[str, str]], cwd: Optional[Path]) -> CommandResult:
    env = dict(os.environ)
    if environment:
        env.update(environment)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        done = subprocess.run(list(command), cwd=str(cwd) if cwd else None, env=env, check=False, capture_output=True, text=True, errors="replace", timeout=60)
        return CommandResult(done.returncode, done.stdout, done.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        return CommandResult(124 if isinstance(error, subprocess.TimeoutExpired) else 126, "", str(error), isinstance(error, subprocess.TimeoutExpired))


def default_execute(command: Sequence[str], environment: Mapping[str, str], cwd: Optional[Path], timeout: int) -> CommandResult:
    try:
        done = subprocess.run(list(command), cwd=str(cwd) if cwd else None, env=dict(environment), check=False, capture_output=True, text=True, errors="replace", timeout=timeout)
        return CommandResult(done.returncode, done.stdout, done.stderr)
    except subprocess.TimeoutExpired as error:
        return CommandResult(124, error.stdout or "", error.stderr or "", True)
    except OSError as error:
        return CommandResult(126, "", str(error))


def runtime_environment(spec: Spec) -> dict[str, str]:
    old = prior.RunSpec(official_root=spec.official_root, binary=spec.binary)
    env = prior.runtime_environment(old)
    # A viewer/display is deliberately unnecessary for this entrypoint.
    env.pop("DISPLAY", None)
    env.pop("XAUTHORITY", None)
    return env


def command_argv(spec: Spec, derived_config: Path) -> list[str]:
    return [str(absolute(spec.binary)), str(absolute(derived_config)), str(absolute(spec.result)).rstrip("/") + "/", str(absolute(spec.sequence)), str(absolute(spec.sequence / "cam0_times.txt"))]


def _parse_ldd(payload: str) -> tuple[dict[str, str], list[str]]:
    resolved, missing = {}, []
    for raw in payload.splitlines():
        line = raw.strip()
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
        elif "=>" in line:
            name, rest = line.split("=>", 1)
            resolved[name.strip()] = rest.strip().split(" ", 1)[0]
    return resolved, missing


def audit_static_contract(spec: Spec, probe: Probe = default_probe) -> dict[str, Any]:
    paths = {"binary": spec.binary, "build_manifest": spec.build_manifest, "official_library": spec.official_library, "config": spec.config, "onnx": spec.onnx, "cache_seed": spec.cache_seed, "official_entry": spec.official_entry, "headless_source": spec.headless_source}
    identities = {name: identity(path) for name, path in paths.items()}
    for name, expected in spec.expected.items():
        if any(identities[name].get(key) != value for key, value in expected.items()):
            raise ContractError(f"FROZEN_IDENTITY_MISMATCH:{name}")
    if not (spec.binary.stat().st_mode & stat.S_IXUSR) or spec.binary.read_bytes()[:4] != b"\x7fELF":
        raise ContractError("HEADLESS_BINARY_NOT_EXECUTABLE_ELF")

    git_commands = {
        "commit": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{commit}"],
        "tree": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{tree}"],
        "origin": ["git", "-C", str(spec.official_root), "remote", "get-url", "origin"],
        "status": ["git", "-C", str(spec.official_root), "status", "--porcelain=v1", "--untracked-files=no"],
    }
    git = {name: probe(cmd, None, None) for name, cmd in git_commands.items()}
    if any(row.returncode != 0 or row.timed_out for row in git.values()):
        raise ContractError("OFFICIAL_GIT_PROBE_FAILED")
    if git["commit"].stdout.strip() != COMMIT or git["tree"].stdout.strip() != TREE or git["origin"].stdout.strip() != ORIGIN or git["status"].stdout.strip():
        raise ContractError("OFFICIAL_SOURCE_IDENTITY_OR_CLEANLINESS_MISMATCH")

    harness = spec.headless_source.read_text(encoding="utf-8")
    required = (": System(settings_file, sensor, false, init_frame)", f'#include "{absolute(spec.official_entry)}"', "#define System HeadlessSystem")
    if any(token not in harness for token in required) or "TrackMonocular(" in harness:
        raise ContractError("HEADLESS_SINGLE_DELTA_STATIC_AUDIT_FAILED")
    config = spec.config.read_text(encoding="utf-8")
    model_path = f'Extractor.modelPath: "{absolute(spec.onnx.parent)}/"'
    frozen_tokens = ('Extractor.type: "HFNetRT"', "Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4", "Extractor.nFeatures: 675", "Extractor.threshold: 0.01", "loopClosing: 1", model_path)
    if any(config.count(token) != 1 for token in frozen_tokens):
        raise ContractError("FROZEN_CONFIG_TOKEN_MISMATCH")

    manifest = json.loads(spec.build_manifest.read_text(encoding="utf-8"))
    if manifest.get("semantic_delta") != {"all_other_entry_logic": "included_from_frozen_official_source", "system_constructor_bUseViewer": False}:
        raise ContractError("BUILD_MANIFEST_SEMANTIC_DELTA_MISMATCH")
    ldd = probe(["ldd", str(absolute(spec.binary))], runtime_environment(spec), None)
    resolved, missing = _parse_ldd(ldd.stdout)
    hfnet = [absolute(Path(path)) for name, path in resolved.items() if name.startswith("libHFNet_SLAM.so")]
    if ldd.returncode != 0 or missing or hfnet != [absolute(spec.official_library)]:
        raise ContractError("HEADLESS_BINARY_LINKAGE_MISMATCH")
    input_audit = prior.audit_input(replace(prior.DEFAULT_SPEC, sequence_root=spec.sequence))
    return {
        "schema_version": PROFILE_SCHEMA,
        "scientific_role": ROLE,
        "baseline": {"commit": COMMIT, "tree": TREE, "origin": ORIGIN},
        "identities": identities,
        "input": input_audit,
        "headless_boundary": {"viewer_enabled": False, "official_entry_included": True, "algorithm_or_threshold_modified": False},
        "runtime_cache_policy": {"classification": "expected_mutable_TensorRT_runtime_artifact", "seed": identities["cache_seed"], "run_local_copy_required": True, "shared_cache_writeback_forbidden": True},
        "runtime": {"display_required": False, "ldd_missing": missing, "official_library_resolved": str(hfnet[0])},
    }


def preflight(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe) -> dict[str, Any]:
    errors = []
    profile = None
    try:
        profile = audit_static_contract(spec, probe)
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
    reservations = {"contract_absent": not spec.contract.exists(), "evidence_absent": not spec.evidence.exists(), "result_absent": not spec.result.exists()}
    if not all(reservations.values()):
        errors.append("OUTPUT_RESERVATION_NOT_EMPTY")
    return {"schema_version": PROFILE_SCHEMA, "status": "PREFLIGHT_READY" if not errors else "PREFLIGHT_BLOCKED", "ready": not errors, "errors": errors, "profile": profile, "reservations": reservations, "claims": {"slam_started": False, "filesystem_writes": False}}


def build_contract(profile: Mapping[str, Any], spec: Spec) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "scientific_role": ROLE,
        "frozen_profile": dict(profile),
        "frozen_profile_sha256": hashlib.sha256(canonical_json(profile).encode()).hexdigest(),
        "execution_policy": {"maximum_process_starts": 1, "retry": False, "viewer": False, "official_algorithm_or_source_modification": False, "cache": "copy seed to run-local model directory; record pre/post SHA; never write back"},
        "paths": {"contract": str(absolute(spec.contract)), "evidence": str(absolute(spec.evidence)), "result": str(absolute(spec.result))},
    }


def freeze(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe) -> dict[str, Any]:
    decision = preflight(spec, probe=probe)
    if not decision["ready"]:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED"}
    contract = build_contract(decision["profile"], spec)
    try:
        write_exclusive(spec.contract, canonical_json(contract).encode())
    except (OSError, FileExistsError) as error:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED", "errors": [*decision["errors"], str(error)]}
    return {"schema_version": SCHEMA, "status": "CONTRACT_FROZEN_NO_RUN_STARTED", "return_code": RC_OK, "contract": identity(spec.contract), "slam_started": False}


def derive_runtime_config(source: str, shared_model_dir: Path, local_model_dir: Path) -> str:
    old = f'Extractor.modelPath: "{absolute(shared_model_dir)}/"'
    new = f'Extractor.modelPath: "{absolute(local_model_dir)}/"'
    if source.count(old) != 1:
        raise ContractError("RUNTIME_CONFIG_MODEL_PATH_REBIND_FAILED")
    derived = source.replace(old, new)
    for token in ("Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4", "Extractor.nFeatures: 675", "Extractor.threshold: 0.01", "loopClosing: 1"):
        if derived.count(token) != 1:
            raise ContractError("RUNTIME_CONFIG_ALGORITHM_TOKEN_DRIFT")
    return derived


def stage_run_local_model(spec: Spec) -> dict[str, Any]:
    model_dir = spec.evidence / "run_local_model/HFNet-RT"
    model_dir.mkdir(parents=True, exist_ok=False)
    local_onnx, local_cache = model_dir / "HF-Net.onnx", model_dir / "HF-Net.cache"
    shutil.copyfile(spec.onnx, local_onnx)
    shutil.copyfile(spec.cache_seed, local_cache)
    os.chmod(local_onnx, 0o444)
    os.chmod(local_cache, 0o644)
    if identity(local_onnx)["sha256"] != identity(spec.onnx)["sha256"] or identity(local_cache)["sha256"] != identity(spec.cache_seed)["sha256"]:
        raise ContractError("RUN_LOCAL_MODEL_COPY_MISMATCH")
    derived_config = spec.evidence / "runtime_config_model_path_only.yaml"
    payload = derive_runtime_config(spec.config.read_text(encoding="utf-8"), spec.onnx.parent, model_dir)
    write_exclusive(derived_config, payload.encode())
    return {"model_dir": model_dir, "onnx": identity(local_onnx), "cache_pre": identity(local_cache), "derived_config": identity(derived_config)}


def run(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe, execute: Execute = default_execute) -> dict[str, Any]:
    try:
        frozen = json.loads(spec.contract.read_text(encoding="utf-8"))
        profile = audit_static_contract(spec, probe)
        if frozen != build_contract(profile, spec):
            raise ContractError("FROZEN_CONTRACT_OR_PROFILE_MISMATCH")
        if spec.evidence.exists() or spec.result.exists():
            raise ContractError("RUN_OUTPUT_NO_CLOBBER")
        spec.evidence.mkdir(parents=True, exist_ok=False)
        write_exclusive(spec.evidence / "frozen_contract.snapshot.json", canonical_json(frozen).encode())
        shared_cache_pre = identity(spec.cache_seed)
        staged = stage_run_local_model(spec)
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as error:
        return {"schema_version": RESULT_SCHEMA, "status": "CONTRACT_BLOCKED", "return_code": RC_BLOCKED, "evaluable": False, "errors": [str(error)], "execution": {"command_started": False}}

    derived_config = Path(staged["derived_config"]["path"])
    command = command_argv(spec, derived_config)
    execution = execute(command, runtime_environment(spec), spec.evidence, spec.timeout_seconds)
    write_exclusive(spec.evidence / "headless.stdout.log", execution.stdout.encode(errors="replace"))
    write_exclusive(spec.evidence / "headless.stderr.log", execution.stderr.encode(errors="replace"))
    cache_post = identity(Path(staged["model_dir"]) / "HF-Net.cache")
    shared_cache_post = identity(spec.cache_seed)
    shared_unchanged = shared_cache_pre == shared_cache_post
    trajectory = prior.audit_trajectory(spec.result / "trajectory.txt")
    keyframes = prior.audit_trajectory(spec.result / "trajectory_keyframe.txt", minimum_pose_count=1)
    passed = (
        execution.returncode == 0
        and not execution.timed_out
        and trajectory.get("gate_pass") is True
        and keyframes.get("finite_eight_field_rows") is True
        and keyframes.get("strictly_increasing_timestamps") is True
        and keyframes.get("pose_count", 0) > 0
        and shared_unchanged
    )
    errors = [] if shared_unchanged else ["SHARED_CACHE_WAS_MODIFIED"]
    result = {
        "schema_version": RESULT_SCHEMA,
        "scientific_role": ROLE,
        "status": "PASS_HEADLESS_TRAJECTORY_GATE" if passed else "HEADLESS_RUN_FAILED_OR_UNUSABLE",
        "return_code": RC_OK if passed else RC_FAILED,
        "evaluable": passed,
        "errors": errors,
        "command_argv": command,
        "execution": {"command_started": True, "process_start_count": 1, "raw_returncode": execution.returncode, "timed_out": execution.timed_out},
        "cache": {"classification": "expected_mutable_TensorRT_runtime_artifact", "shared_pre": shared_cache_pre, "shared_post": shared_cache_post, "shared_unchanged": shared_unchanged, "run_local_pre": staged["cache_pre"], "run_local_post": cache_post, "writeback_performed": False},
        "immutables": {"profile_sha256": frozen["frozen_profile_sha256"], "run_local_onnx": staged["onnx"], "derived_config": staged["derived_config"]},
        "gate": {"trajectory": trajectory, "keyframe_trajectory": keyframes, "return_code_zero": execution.returncode == 0},
        "supervision": {"viewer_enabled": False, "algorithm_or_official_source_modified": False, "retry_performed": False},
    }
    write_exclusive(spec.evidence / "run_result.json", canonical_json(result).encode())
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("preflight", "freeze", "run"), default="preflight")
    value.add_argument("--sequence-root", type=Path, default=DEFAULT_SEQUENCE)
    value.add_argument("--result-directory", type=Path, default=DEFAULT_RESULT)
    value.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE)
    value.add_argument("--contract-json", type=Path, default=DEFAULT_CONTRACT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    spec = replace(DEFAULT_SPEC, sequence=args.sequence_root, result=args.result_directory, evidence=args.evidence_directory, contract=args.contract_json)
    decision = preflight(spec) if args.action == "preflight" else freeze(spec) if args.action == "freeze" else run(spec)
    if args.action == "preflight":
        decision["return_code"] = RC_OK if decision["ready"] else RC_BLOCKED
    sys.stdout.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
