#!/usr/bin/env python3
"""Prospective, cache-only adjudicator for the nine unstarted HFNet-v6 cases.

The frozen v2 runner correctly requires the attempt-local TensorRT cache to
equal the shared seed before the only child starts, but its inherited post-run
audit also requires the cache to retain that seed hash.  Stock HFNet-SLAM
updates this isolated timing cache while it builds the four pyramid engines.

This controller adds two no-clobber evidence boundaries without modifying the
v2 runner, any prepared manifest, or its terminal result:

``check-prestart`` / ``freeze-prestart``
    Validate (and optionally freeze) the exact seed and all immutable inputs
    before a remaining case starts.

``check-post`` / ``publish-post``
    Revalidate all immutable inputs after the v2 terminal result, audit the
    exact four-model timing-cache event stream, and issue an independent
    runability receipt.  Only the cache-specific v2 post-audit error and its
    two consequent failure codes may be carved out.

A05 is deliberately excluded.  Its consumed signal/empty-atlas failure cannot
be re-adjudicated or retried.  A PASS receipt from this script is not accepted
by the already-published accuracy seal unless a later prospective accuracy
authority explicitly pins and adopts it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = Path(__file__).resolve()
V2_RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"
V2_RUNNER_IDENTITY = {
    "path": str(V2_RUNNER),
    "size_bytes": 7_639,
    "sha256": "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
}
ADDENDUM = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_cache_contract_prospective_addendum_v1.md"
)
ADDENDUM_IDENTITY = {
    "path": str(ADDENDUM),
    "size_bytes": 5_666,
    "sha256": "3efbf2e0d31548b5c12d9f0ca9f6ff344a82b9453ff4f475a986c6b774ab4dea",
}
WATCHDOG = (
    ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py"
)
WATCHDOG_IDENTITY = {
    "path": str(WATCHDOG),
    "size_bytes": 35_087,
    "sha256": "a85c6620fb16bb3c2525e654342aa22ab816684030d41bc598ead752fc399b71",
}
WATCHDOG_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_zero_kf_save_hang_watchdog_protocol_v1.md"
)
WATCHDOG_PROTOCOL_IDENTITY = {
    "path": str(WATCHDOG_PROTOCOL),
    "size_bytes": 5_967,
    "sha256": "ef328399e1bb23209fd3481426b6d91df6919b0a9dff8685392fd51dc47bf82a",
}
HFNET_RT_SOURCE_IDENTITY = {
    "path": "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/src/Extractors/HFNetRTModel.cc",
    "size_bytes": 16_872,
    "sha256": "a903a8ac84ad9f7c14e707091acf5fee25ab511607b9377baffebad8df135155",
}
BASE_MODEL_SOURCE_IDENTITY = {
    "path": "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/src/Extractors/BaseModel.cc",
    "size_bytes": 19_609,
    "sha256": "677628c45e1c1707d8bdc82a7fffc51dc1ea0f852c4338dfe13c138cddde74ae",
}
RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
RECEIPT_ROOT = RUNTIME_ROOT / "_cache_contract_adjudication_v1"
WATCHDOG_RECEIPT_ROOT = RUNTIME_ROOT / "_zero_kf_save_hang_watchdog_v1"
WATCHDOG_ROSTER_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
WATCHDOG_ACCURACY_PREFREEZE_SEAL = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
)

PROSPECTIVE_CASES = (
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
)
EXCLUDED_CONSUMED_CASE = "a05_3300_3700"
PRESTART_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-prestart-v1"
)
ADJUDICATION_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-adjudication-v1"
)
WATCHDOG_RECEIPT_SCHEMA = (
    "aqua-fe-hfnet-v6-zero-kf-save-hang-watchdog-receipt-v1"
)
WATCHDOG_PASSIVE_STATUS = "PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL"
WATCHDOG_ZERO_KF_STATUS = "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_SAVE_HANG"
FREEZE_TOKEN = "FREEZE_HFNET_V6_SAMEHISTORY_CACHE_CONTRACT_PRESTART_V1"
PUBLISH_TOKEN = "PUBLISH_HFNET_V6_SAMEHISTORY_CACHE_ADJUDICATION_V1"
EXPECTED_CACHE_POST_ERROR = (
    "FROZEN_CONTRACT_POST_AUDIT:ContractError:DERIVED_FILE_DRIFT:local_cache"
)
CACHE_CONSEQUENT_FAILURE_CODES = (
    "FROZEN_CONTRACT_DRIFT",
    "POST_AUDIT_INCOMPLETE",
)
EXPECTED_MODEL_LEVELS = 4
ACCURACY_SUPERSESSION = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_supersession_v2.json"
)


class ContractError(RuntimeError):
    """Fail-closed validation error with a stable code."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def require_exact_keys(value: Mapping[str, Any], expected: Sequence[str], label: str) -> None:
    require(set(value) == set(expected), f"OBJECT_KEYS:{label}")


def parse_canonical_utc_second(value: Any, label: str) -> datetime:
    require(isinstance(value, str), f"UTC_TIMESTAMP_TYPE:{label}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContractError(f"UTC_TIMESTAMP_PARSE:{label}") from error
    require(parsed.tzinfo is not None, f"UTC_TIMESTAMP_NAIVE:{label}")
    require(parsed.utcoffset() == timezone.utc.utcoffset(parsed), f"UTC_TIMESTAMP_NOT_UTC:{label}")
    require(parsed.isoformat(timespec="seconds") == value, f"UTC_TIMESTAMP_NOT_CANONICAL:{label}")
    return parsed


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Snapshot:
    path: str
    size_bytes: int
    sha256: str
    st_dev: int
    st_ino: int
    st_mode: int
    st_nlink: int
    st_mtime_ns: int

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @property
    def stat_binding(self) -> dict[str, int]:
        return {
            "st_dev": self.st_dev,
            "st_ino": self.st_ino,
            "st_mode": self.st_mode,
            "st_nlink": self.st_nlink,
            "st_mtime_ns": self.st_mtime_ns,
        }

    @property
    def evidence(self) -> dict[str, Any]:
        return {"identity": self.identity, "stat_binding": self.stat_binding}


def snapshot_regular(path: Path, label: str) -> Snapshot:
    require(path.is_absolute(), f"PATH_NOT_ABSOLUTE:{label}")
    try:
        metadata = os.lstat(str(path))
    except OSError as error:
        raise ContractError(f"FILE_LSTAT_FAILED:{label}:{type(error).__name__}") from error
    require(not stat.S_ISLNK(metadata.st_mode), f"FILE_SYMLINK:{label}")
    require(stat.S_ISREG(metadata.st_mode), f"FILE_NOT_REGULAR:{label}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ContractError(f"PATH_RESOLVE_FAILED:{label}:{type(error).__name__}") from error
    require(str(resolved) == str(path), f"PATH_NOT_CANONICAL:{label}")
    return Snapshot(
        path=str(path),
        size_bytes=metadata.st_size,
        sha256=sha256_file(path),
        st_dev=metadata.st_dev,
        st_ino=metadata.st_ino,
        st_mode=metadata.st_mode,
        st_nlink=metadata.st_nlink,
        st_mtime_ns=metadata.st_mtime_ns,
    )


def require_identity(snapshot: Snapshot, expected: Mapping[str, Any], label: str) -> None:
    require(
        snapshot.identity
        == {
            "path": str(expected.get("path")),
            "size_bytes": expected.get("size_bytes"),
            "sha256": expected.get("sha256"),
        },
        f"IDENTITY_MISMATCH:{label}",
    )


def read_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], Snapshot]:
    snapshot = snapshot_regular(path, label)
    payload = path.read_bytes()
    require(
        len(payload) == snapshot.size_bytes and sha256_bytes(payload) == snapshot.sha256,
        f"JSON_CHANGED_DURING_READ:{label}",
    )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"JSON_PARSE:{label}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{label}")
    require(canonical_json_bytes(value) == payload, f"JSON_NOT_CANONICAL:{label}")
    return value, snapshot


def _load_v2() -> Any:
    require_identity(snapshot_regular(V2_RUNNER, "v2_runner"), V2_RUNNER_IDENTITY, "v2_runner")
    sys.dont_write_bytecode = True
    specification = importlib.util.spec_from_file_location(
        "_hfnet_v6_cache_adjudicator_pinned_v2", V2_RUNNER
    )
    require(specification is not None and specification.loader is not None, "V2_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


V2 = _load_v2()
BASE = V2._v1


def prestart_receipt_path(case_id: str) -> Path:
    return RECEIPT_ROOT / f"{case_id}.prestart.json"


def adjudication_receipt_path(case_id: str) -> Path:
    return RECEIPT_ROOT / f"{case_id}.runability_adjudication.json"


def watchdog_receipt_path(case_id: str) -> Path:
    return WATCHDOG_RECEIPT_ROOT / f"{case_id}.json"


def validate_accuracy_supersession(case_id: str) -> Snapshot:
    value, snapshot = read_canonical_json(
        ACCURACY_SUPERSESSION, "accuracy_authority_supersession"
    )
    require(
        value.get("schema_version")
        == "aqua-fe-hfnet-v6-samehistory-positive-accuracy-supersession-v2",
        "ACCURACY_SUPERSESSION_SCHEMA",
    )
    require(
        value.get("status")
        == "SEALED_POST_A05_CACHE_VALIDATOR_INCIDENT_BEFORE_REMAINING_NINE_NO_METRICS",
        "ACCURACY_SUPERSESSION_STATUS",
    )
    require(value.get("remaining_cases") == list(PROSPECTIVE_CASES), "ACCURACY_SUPERSESSION_CASES")
    require(case_id in value.get("remaining_cases", []), "ACCURACY_SUPERSESSION_CASE_NOT_AUTHORIZED")
    require(isinstance(value.get("a05_terminal_boundary"), Mapping), "ACCURACY_SUPERSESSION_A05_BOUNDARY")
    identities = value.get("analysis_code_identities")
    require(isinstance(identities, Mapping), "ACCURACY_SUPERSESSION_CODE_IDENTITIES")
    require(
        identities.get("cache_contract_adjudicator")
        == snapshot_regular(VALIDATOR, "validator_self").identity,
        "ACCURACY_SUPERSESSION_VALIDATOR_IDENTITY",
    )
    require(
        isinstance(identities.get("formal_accuracy_controller_v2"), Mapping),
        "ACCURACY_SUPERSESSION_CONTROLLER_V2_IDENTITY",
    )
    require(
        identities.get("zero_kf_watchdog") == dict(WATCHDOG_IDENTITY),
        "ACCURACY_SUPERSESSION_WATCHDOG_IDENTITY",
    )
    authorities = value.get("authorities")
    require(isinstance(authorities, Mapping), "ACCURACY_SUPERSESSION_AUTHORITIES")
    require(
        authorities.get("cache_contract_governance_addendum")
        == dict(ADDENDUM_IDENTITY),
        "ACCURACY_SUPERSESSION_CACHE_ADDENDUM",
    )
    require(
        authorities.get("zero_kf_watchdog_protocol")
        == dict(WATCHDOG_PROTOCOL_IDENTITY),
        "ACCURACY_SUPERSESSION_WATCHDOG_PROTOCOL",
    )
    require(
        value.get("zero_kf_watchdog_contract")
        == {
            "accuracy_promotable_status": WATCHDOG_PASSIVE_STATUS,
            "pass_requires_runner_reaped": True,
            "pass_requires_zero_signal_attempts": True,
            "pass_requires_zero_signals": True,
            "pass_requires_empty_monitoring_errors": True,
            "raw_runability_receipt_exact_pin_required": True,
            "supervisor_pre_post_exact_code_identity_required": True,
            "runner_claim_chain_exactly_validated_by_adjudicator": True,
            "zero_kf_or_supervision_error_promotable": False,
        },
        "ACCURACY_SUPERSESSION_WATCHDOG_CONTRACT",
    )
    return snapshot


def _case_id(spec: Mapping[str, Any]) -> str:
    case_id = str(spec.get("case_id"))
    require(case_id != EXCLUDED_CONSUMED_CASE, "A05_CONSUMED_RE_ADJUDICATION_FORBIDDEN")
    require(case_id in PROSPECTIVE_CASES, "CASE_NOT_IN_PROSPECTIVE_NINE")
    return case_id


def _snapshot_identity(path: Path, expected: Mapping[str, Any], label: str) -> Snapshot:
    observed = snapshot_regular(path, label)
    require_identity(observed, expected, label)
    return observed


def audit_model_directory(
    local_onnx: Path,
    local_cache: Path,
    shared_cache: Path,
    expected_onnx: Mapping[str, Any],
    expected_seed: Mapping[str, Any],
    *,
    require_seed: bool,
) -> dict[str, Any]:
    """Validate strict two-file closure and cache isolation."""

    directory = local_onnx.parent
    require(directory == local_cache.parent, "LOCAL_MODEL_PARENT_MISMATCH")
    require(directory.is_absolute(), "LOCAL_MODEL_DIRECTORY_NOT_ABSOLUTE")
    try:
        directory_metadata = os.lstat(str(directory))
    except OSError as error:
        raise ContractError("LOCAL_MODEL_DIRECTORY_LSTAT") from error
    require(not stat.S_ISLNK(directory_metadata.st_mode), "LOCAL_MODEL_DIRECTORY_SYMLINK")
    require(stat.S_ISDIR(directory_metadata.st_mode), "LOCAL_MODEL_DIRECTORY_NOT_DIRECTORY")
    require(str(directory.resolve(strict=True)) == str(directory), "LOCAL_MODEL_DIRECTORY_NOT_CANONICAL")

    entries = list(directory.iterdir())
    require(
        {entry.name for entry in entries} == {"HF-Net.onnx", "HF-Net.cache"},
        "LOCAL_MODEL_DIRECTORY_CLOSURE",
    )
    for entry in entries:
        metadata = os.lstat(str(entry))
        require(not stat.S_ISLNK(metadata.st_mode), f"LOCAL_MODEL_ENTRY_SYMLINK:{entry.name}")
        require(stat.S_ISREG(metadata.st_mode), f"LOCAL_MODEL_ENTRY_NOT_REGULAR:{entry.name}")

    onnx = _snapshot_identity(local_onnx, expected_onnx, "local_onnx")
    cache = snapshot_regular(local_cache, "local_cache")
    shared = _snapshot_identity(shared_cache, expected_seed, "shared_cache_seed")
    require((cache.st_dev, cache.st_ino) != (shared.st_dev, shared.st_ino), "LOCAL_CACHE_ALIASES_SHARED_SEED")
    require((cache.st_dev, cache.st_ino) != (onnx.st_dev, onnx.st_ino), "LOCAL_CACHE_ALIASES_ONNX")
    require(cache.size_bytes > 0, "LOCAL_CACHE_EMPTY")
    if require_seed:
        require(
            cache.size_bytes == shared.size_bytes and cache.sha256 == shared.sha256,
            "LOCAL_CACHE_PRESTART_NOT_EXACT_SEED",
        )
    return {
        "directory": str(directory),
        "closure": ["HF-Net.cache", "HF-Net.onnx"],
        "local_onnx": onnx.evidence,
        "local_cache": cache.evidence,
        "shared_cache_seed": shared.evidence,
        "local_cache_isolated_from_shared_seed": True,
        "local_cache_matches_shared_seed": (
            cache.size_bytes == shared.size_bytes and cache.sha256 == shared.sha256
        ),
    }


def require_local_cache_in_place(
    pre_model: Mapping[str, Any], post_model: Mapping[str, Any]
) -> None:
    pre_cache_stat = pre_model.get("local_cache", {}).get("stat_binding", {})
    post_cache_stat = post_model.get("local_cache", {}).get("stat_binding", {})
    require(
        (post_cache_stat.get("st_dev"), post_cache_stat.get("st_ino"))
        == (pre_cache_stat.get("st_dev"), pre_cache_stat.get("st_ino")),
        "LOCAL_CACHE_INODE_REPLACED_SINCE_PRESTART",
    )
    require(
        post_cache_stat.get("st_mode") == pre_cache_stat.get("st_mode"),
        "LOCAL_CACHE_MODE_CHANGED_SINCE_PRESTART",
    )
    require(
        post_cache_stat.get("st_nlink") == pre_cache_stat.get("st_nlink"),
        "LOCAL_CACHE_LINK_COUNT_CHANGED_SINCE_PRESTART",
    )


def immutable_prepared_contract(
    spec_path: Path, *, require_cache_seed: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path]]:
    """Revalidate v2 preparation while excluding only post-run cache bytes."""

    spec, prepared = BASE.load_prepared(spec_path)
    _case_id(spec)
    paths = BASE.attempt_paths(spec)
    require(not paths["root"].is_symlink() and paths["root"].is_dir(), "ATTEMPT_ROOT_INVALID")
    require(
        not paths["result_dir"].is_symlink() and paths["result_dir"].is_dir(),
        "RESULT_DIRECTORY_INVALID",
    )
    require(prepared.get("status") == "PREPARED_NOT_STARTED", "PREPARED_STATUS")
    require(prepared.get("case_id") == spec.get("case_id"), "PREPARED_CASE")
    require(prepared.get("case_spec") == BASE.identity(spec_path), "CASE_SPEC_DRIFT")
    runner = BASE.identity(V2_RUNNER)
    require(prepared.get("runner") == runner, "PREPARED_RUNNER_DRIFT")
    stack = BASE.require_stack()
    require(prepared.get("stack") == stack, "PREPARED_STACK_DRIFT")
    dependencies = BASE.require_frozen_dependencies(
        spec_path, spec, Path(str(spec["input_root"]))
    )
    require(prepared.get("frozen_dependencies") == dependencies, "FROZEN_DEPENDENCY_DRIFT")
    stamps = BASE.selected_timestamps(spec)
    inventory = BASE.input_inventory(spec, stamps)
    require(prepared.get("input_inventory") == inventory, "INPUT_INVENTORY_DRIFT")
    expected_derived = BASE.canonical_derived(spec, paths)
    require(prepared.get("derived") == expected_derived, "PREPARED_DERIVED_CONTRACT")
    for path_key, derived_key in (
        ("runtime_config", "runtime_config"),
        ("local_model", "local_onnx"),
    ):
        require(
            BASE.identity(paths[path_key]) == expected_derived[derived_key],
            f"IMMUTABLE_DERIVED_DRIFT:{derived_key}",
        )
    launch = BASE.canonical_launch(spec, paths)
    scientific = BASE.canonical_scientific_boundary(spec)
    require(prepared.get("launch") == launch, "PREPARED_LAUNCH_DRIFT")
    require(prepared.get("scientific_boundary") == scientific, "SCIENTIFIC_BOUNDARY_DRIFT")
    if require_cache_seed:
        # Exercise the frozen v2 contract itself at the prospective boundary.
        BASE.require_prepared_contract(spec_path, spec, prepared)
    immutable = {
        "case_spec": BASE.identity(spec_path),
        "prepared_manifest": BASE.identity(paths["prepared"]),
        "runner": runner,
        "stack": stack,
        "frozen_dependencies": dependencies,
        "input_inventory": inventory,
        "derived_declarations": expected_derived,
        "launch": launch,
        "scientific_boundary": scientific,
    }
    return spec, prepared, immutable, paths


def _require_absent(path: Path, label: str) -> None:
    require(not path.exists() and not path.is_symlink(), f"PRESTART_ARTIFACT_EXISTS:{label}")


def validate_prestart(spec_path: Path) -> dict[str, Any]:
    spec, prepared, immutable, paths = immutable_prepared_contract(
        spec_path, require_cache_seed=True
    )
    case_id = _case_id(spec)
    model = audit_model_directory(
        paths["local_model"],
        paths["local_cache"],
        Path(str(prepared["stack"]["shared_cache"]["path"])),
        prepared["derived"]["local_onnx"],
        prepared["stack"]["shared_cache"],
        require_seed=True,
    )
    permanent = BASE.permanent_case_paths(case_id)
    for label, path in (
        ("attempt_claim", paths["claim"]),
        ("run_result", paths["result"]),
        ("stdout", paths["stdout"]),
        ("stderr", paths["stderr"]),
        ("permanent_reservation", permanent["reservation"]),
        ("permanent_claim", permanent["claim"]),
        ("trajectory", paths["result_dir"] / "trajectory.txt"),
        ("keyframe_trajectory", paths["result_dir"] / "trajectory_keyframe.txt"),
        ("preparation_incident", paths["prepare_incident"]),
        ("post_adjudication", adjudication_receipt_path(case_id)),
        ("zero_kf_watchdog_receipt", watchdog_receipt_path(case_id)),
    ):
        _require_absent(path, label)
    require(not any(paths["result_dir"].iterdir()), "PRESTART_RESULT_DIRECTORY_NOT_EMPTY")
    for expected in (
        ADDENDUM_IDENTITY,
        WATCHDOG_IDENTITY,
        WATCHDOG_PROTOCOL_IDENTITY,
        HFNET_RT_SOURCE_IDENTITY,
        BASE_MODEL_SOURCE_IDENTITY,
    ):
        _snapshot_identity(Path(str(expected["path"])), expected, Path(str(expected["path"])).name)
    accuracy_supersession = validate_accuracy_supersession(case_id)
    return {
        "schema_version": PRESTART_SCHEMA,
        "status": "PASS_PROSPECTIVE_CACHE_SEED_BOUNDARY_NOT_STARTED",
        "case_id": case_id,
        "validator": snapshot_regular(VALIDATOR, "validator_self").identity,
        "governance_addendum": dict(ADDENDUM_IDENTITY),
        "zero_kf_watchdog": dict(WATCHDOG_IDENTITY),
        "zero_kf_watchdog_protocol": dict(WATCHDOG_PROTOCOL_IDENTITY),
        "v2_runner": dict(V2_RUNNER_IDENTITY),
        "stock_cache_source": dict(HFNET_RT_SOURCE_IDENTITY),
        "four_level_constructor_source": dict(BASE_MODEL_SOURCE_IDENTITY),
        "accuracy_authority_supersession": accuracy_supersession.identity,
        "immutable_prepared_contract": immutable,
        "model_directory": model,
        "attempt_not_started": True,
        "a05_retroactive_adjudication_permitted": False,
        "retry_permitted": False,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_publish_noreplace(path: Path, value: Mapping[str, Any]) -> Snapshot:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.parent.is_symlink() and path.parent.is_dir(), "PUBLICATION_PARENT_INVALID")
    payload = canonical_json_bytes(value)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.publish-", dir=str(path.parent))
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        require(temporary.read_bytes() == payload, "TEMPORARY_PUBLICATION_BYTES")
        try:
            os.link(str(temporary), str(path), follow_symlinks=False)
        except FileExistsError as error:
            raise ContractError("EXCLUSIVE_PUBLICATION_EXISTS") from error
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if published:
            _fsync_directory(path.parent)
    snapshot = snapshot_regular(path, "published_receipt")
    require(snapshot.size_bytes == len(payload) and snapshot.sha256 == sha256_bytes(payload), "PUBLISHED_BYTES_DRIFT")
    return snapshot


def freeze_prestart(spec_path: Path) -> dict[str, Any]:
    with BASE.global_serial_lock() as lock:
        first = validate_prestart(spec_path)
        case_id = str(first["case_id"])
        destination = prestart_receipt_path(case_id)
        _require_absent(destination, "prestart_receipt")
        second = validate_prestart(spec_path)
        require(first == second, "PRESTART_TOCTOU_DRIFT")
        value = {
            **second,
            "status": "FROZEN_PROSPECTIVE_CACHE_SEED_BOUNDARY_NOT_STARTED",
            "frozen_at_utc": BASE.now_utc(),
            "roster_global_lock": lock,
        }
        published = atomic_publish_noreplace(destination, value)
    return {**value, "receipt_identity": published.identity}


LOADED_PATTERN = re.compile(r"^Loaded ([0-9]+) bytes of timing cache from (.+)$")
SAVED_PATTERN = re.compile(r"^Saved ([0-9]+) bytes of timing cache to (.+)$")


def _normalize_logged_cache_path(raw: str, expected: Path) -> str:
    require(raw.startswith("/"), "TIMING_CACHE_PATH_NOT_ABSOLUTE")
    require("\x00" not in raw, "TIMING_CACHE_PATH_NUL")
    require(os.path.normpath(raw) == str(expected), "TIMING_CACHE_PATH_NOT_CANONICAL_LOCAL")
    return str(expected)


def audit_timing_cache_events(
    stderr_payload: bytes,
    stdout_payload: bytes,
    expected_cache: Path,
    seed_size: int,
    post_size: int,
) -> dict[str, Any]:
    try:
        stderr_lines = stderr_payload.decode("utf-8").splitlines()
        stdout_lines = stdout_payload.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise ContractError("HFNET_LOG_UTF8") from error
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(stderr_lines, start=1):
        if "timing cache" not in line.lower():
            continue
        loaded = LOADED_PATTERN.fullmatch(line)
        saved = SAVED_PATTERN.fullmatch(line)
        require((loaded is None) != (saved is None), f"TIMING_CACHE_MESSAGE_UNRECOGNIZED:{line_number}")
        match = loaded if loaded is not None else saved
        assert match is not None
        events.append(
            {
                "kind": "LOADED" if loaded is not None else "SAVED",
                "size_bytes": int(match.group(1)),
                "path": _normalize_logged_cache_path(match.group(2), expected_cache),
                "stderr_line": line_number,
            }
        )
    expected_kinds = [kind for _ in range(EXPECTED_MODEL_LEVELS) for kind in ("LOADED", "LOADED", "SAVED")]
    require([event["kind"] for event in events] == expected_kinds, "TIMING_CACHE_EVENT_SEQUENCE")
    expected_input_size = seed_size
    groups: list[dict[str, Any]] = []
    for level in range(EXPECTED_MODEL_LEVELS):
        first, second, saved = events[level * 3 : level * 3 + 3]
        require(first["size_bytes"] == expected_input_size, f"TIMING_CACHE_FIRST_LOAD_SIZE:{level}")
        require(second["size_bytes"] == expected_input_size, f"TIMING_CACHE_UPDATE_LOAD_SIZE:{level}")
        require(saved["size_bytes"] >= expected_input_size, f"TIMING_CACHE_SAVE_SHRANK:{level}")
        expected_input_size = saved["size_bytes"]
        groups.append(
            {
                "pyramid_level": level,
                "loaded_size_bytes": first["size_bytes"],
                "saved_size_bytes": saved["size_bytes"],
                "stderr_lines": [first["stderr_line"], second["stderr_line"], saved["stderr_line"]],
            }
        )
    require(expected_input_size == post_size, "TIMING_CACHE_FINAL_SIZE_NOT_POST_FILE")
    successful_models = sum(
        line.startswith("Successfully loaded HFNet TensorRT model.") for line in stdout_lines
    )
    require(successful_models == EXPECTED_MODEL_LEVELS, "HFNET_SUCCESSFUL_MODEL_COUNT_NOT_FOUR")
    return {
        "expected_cache_path": str(expected_cache),
        "pyramid_model_count": EXPECTED_MODEL_LEVELS,
        "event_count": len(events),
        "events": events,
        "groups": groups,
        "successful_model_log_count": successful_models,
        "read_or_write_error_observed": False,
    }


def derive_failure_codes(
    raw_failure_codes: Sequence[Any],
    post_audit_errors: Sequence[Any],
    *,
    cache_changed: bool,
) -> tuple[list[str], list[str], bool]:
    require(
        all(isinstance(value, str) for value in raw_failure_codes),
        "RUN_RESULT_FAILURE_CODE_TYPE",
    )
    raw = list(raw_failure_codes)
    require(len(raw) == len(set(raw)), "RUN_RESULT_FAILURE_CODE_DUPLICATE")
    require(
        all(isinstance(value, str) for value in post_audit_errors),
        "RUN_RESULT_POST_AUDIT_ERROR_TYPE",
    )
    errors = list(post_audit_errors)
    cache_only = cache_changed and errors == [EXPECTED_CACHE_POST_ERROR]
    carved: list[str] = []
    retained = list(raw)
    if cache_only:
        for code in CACHE_CONSEQUENT_FAILURE_CODES:
            require(code in retained, f"CACHE_CONSEQUENT_FAILURE_MISSING:{code}")
            retained.remove(code)
            carved.append(code)
    elif errors:
        retained.append("NON_CACHE_OR_UNPROVEN_POST_AUDIT_ERROR")
    require(
        not (cache_changed and not errors),
        "CACHE_CHANGED_WITHOUT_FROZEN_V2_POST_AUDIT_ERROR",
    )
    return retained, carved, cache_only


def independent_scientific_runability_audit(
    spec: Mapping[str, Any], paths: Mapping[str, Path], raw_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Recompute every non-integrity v2 runability gate from raw artifacts."""

    stamps = BASE.selected_timestamps(spec)
    trajectory = V2.parse_trajectory(paths["result_dir"] / "trajectory.txt", stamps)
    keyframes = V2.parse_trajectory(
        paths["result_dir"] / "trajectory_keyframe.txt", stamps
    )
    log = BASE.parse_log(paths["stdout"])
    accepted = BASE.events_in_accepted_support(log, trajectory)
    log["accepted_support_first_relative_index"] = accepted["first_relative_index"]
    log["accepted_support_last_relative_index"] = accepted["last_relative_index"]
    log["proven_early_reset_events"] = accepted["proven_early_reset_events"]
    log["accepted_support_unresolved_reset_events"] = accepted["unresolved_reset_events"]
    log["accepted_support_reinitialization_frame_ids"] = accepted[
        "reinitialization_frame_ids"
    ]
    support = {
        "camera_count": len(stamps),
        "trajectory": trajectory,
        "keyframes": keyframes,
        "log": log,
    }
    require(raw_result.get("support") == support, "RAW_SUPPORT_NOT_INDEPENDENT_REPARSE")

    execution = raw_result.get("execution")
    require(isinstance(execution, Mapping), "RUN_RESULT_EXECUTION_NOT_OBJECT")
    failures: list[str] = []
    if (
        execution.get("raw_returncode") != 0
        or execution.get("timed_out") is True
        or execution.get("supervisor_error") is not None
        or execution.get("child_reaped_before_post_audit") is not True
        or execution.get("popen_invocations") != 1
    ):
        failures.append("EXECUTION_NOT_CLEAN")
    if trajectory.get("valid") is not True:
        failures.append("TRAJECTORY_INVALID")
    if float(trajectory.get("coverage_fraction", 0.0)) < BASE.MIN_COVERAGE:
        failures.append("TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
    if float(trajectory.get("longest_contiguous_fraction", 0.0)) < BASE.MIN_CONTIGUOUS:
        failures.append("TRAJECTORY_CONTIGUOUS_SUPPORT_BELOW_70_PERCENT")
    if keyframes.get("valid") is not True or int(keyframes.get("pose_count", 0)) < 1:
        failures.append("NO_VALID_KEYFRAME_TRAJECTORY")
    if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
        failures.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
    if int(log.get("initialization_count", 0)) < 1:
        failures.append("NO_SUCCESSFUL_INITIALIZATION")
    if accepted["unresolved_reset_events"]:
        failures.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
    if accepted["reinitialization_frame_ids"]:
        failures.append("REINITIALIZATION_WITHIN_ACCEPTED_SUPPORT")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "support": support,
        "all_scientific_runability_conditions_recomputed": True,
        "raw_runner_support_accepted_without_reparse": False,
    }


def _verify_prestart_receipt(case_id: str) -> tuple[dict[str, Any], Snapshot]:
    path = prestart_receipt_path(case_id)
    value, snapshot = read_canonical_json(path, "cache_prestart_receipt")
    require(value.get("schema_version") == PRESTART_SCHEMA, "PRESTART_RECEIPT_SCHEMA")
    require(
        value.get("status") == "FROZEN_PROSPECTIVE_CACHE_SEED_BOUNDARY_NOT_STARTED",
        "PRESTART_RECEIPT_STATUS",
    )
    require(value.get("case_id") == case_id, "PRESTART_RECEIPT_CASE")
    require(value.get("attempt_not_started") is True, "PRESTART_RECEIPT_NOT_UNSTARTED")
    require(value.get("retry_permitted") is False, "PRESTART_RECEIPT_RETRY")
    require(value.get("a05_retroactive_adjudication_permitted") is False, "PRESTART_RECEIPT_A05_POLICY")
    require_identity(
        snapshot_regular(Path(str(value["validator"]["path"])), "prestart_validator"),
        value["validator"],
        "prestart_validator",
    )
    require(value.get("validator") == snapshot_regular(VALIDATOR, "validator_self").identity, "VALIDATOR_CHANGED_SINCE_PRESTART")
    for key, expected in (
        ("governance_addendum", ADDENDUM_IDENTITY),
        ("zero_kf_watchdog", WATCHDOG_IDENTITY),
        ("zero_kf_watchdog_protocol", WATCHDOG_PROTOCOL_IDENTITY),
        ("v2_runner", V2_RUNNER_IDENTITY),
        ("stock_cache_source", HFNET_RT_SOURCE_IDENTITY),
        ("four_level_constructor_source", BASE_MODEL_SOURCE_IDENTITY),
    ):
        require(value.get(key) == dict(expected), f"PRESTART_AUTHORITY_FIELD:{key}")
        _snapshot_identity(Path(str(expected["path"])), expected, key)
    accuracy_supersession = validate_accuracy_supersession(case_id)
    require(
        value.get("accuracy_authority_supersession")
        == accuracy_supersession.identity,
        "PRESTART_ACCURACY_SUPERSESSION_IDENTITY",
    )
    return value, snapshot


def _validate_runner_receipts(
    case_id: str,
    spec_path: Path,
    prepared: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> tuple[dict[str, Any], Snapshot, Snapshot, Snapshot, Snapshot, Snapshot]:
    result, result_snapshot = read_canonical_json(paths["result"], "v2_run_result")
    claim, claim_snapshot = read_canonical_json(paths["claim"], "attempt_process_claim")
    permanent = BASE.permanent_case_paths(case_id)
    permanent_claim, permanent_claim_snapshot = read_canonical_json(
        permanent["claim"], "permanent_process_claim"
    )
    reservation_snapshot = snapshot_regular(permanent["reservation"], "permanent_start_reservation")
    prepared_snapshot = snapshot_regular(paths["prepared"], "prepared_manifest")
    require(result.get("schema_version") == V2.RESULT_SCHEMA, "RUN_RESULT_SCHEMA")
    require(result.get("case_id") == case_id, "RUN_RESULT_CASE")
    terminal = result.get("terminal_contract")
    require(
        isinstance(terminal, Mapping)
        and terminal.get("attempt_consumed") is True
        and terminal.get("retry_after_pass_or_fail") is False
        and terminal.get("claim_without_result_is_terminal_fail") is True,
        "RUN_RESULT_NOT_TERMINAL",
    )
    require(claim.get("schema_version") == V2.CLAIM_SCHEMA, "PROCESS_CLAIM_SCHEMA")
    require(claim.get("case_id") == case_id, "PROCESS_CLAIM_CASE")
    require(claim == permanent_claim, "PROCESS_CLAIM_COPY_MISMATCH")
    require(claim.get("maximum_popen_invocations") == 1, "PROCESS_CLAIM_POPEN_LIMIT")
    require(claim.get("retry_permitted") is False, "PROCESS_CLAIM_RETRY")
    require(claim.get("prepared_manifest") == prepared_snapshot.identity, "PROCESS_CLAIM_PREPARED_PIN")
    require(claim.get("runner") == dict(V2_RUNNER_IDENTITY), "PROCESS_CLAIM_RUNNER_PIN")
    require(claim.get("launch") == prepared.get("launch"), "PROCESS_CLAIM_LAUNCH")
    precheck = claim.get("prestart_check")
    require(
        isinstance(precheck, Mapping)
        and precheck.get("ready") is True
        and precheck.get("errors") == [],
        "PROCESS_CLAIM_PRESTART_CHECK",
    )
    require(result.get("prestart_check") == precheck, "RUN_RESULT_PRECHECK_MISMATCH")
    execution = result.get("execution")
    require(
        isinstance(execution, Mapping)
        and execution.get("popen_invocations") == 1
        and execution.get("retry_performed") is False
        and execution.get("retry_permitted") is False
        and execution.get("child_reaped_before_post_audit") is True,
        "RUN_RESULT_EXECUTION_BOUNDARY",
    )
    pins = result.get("pins")
    require(isinstance(pins, Mapping), "RUN_RESULT_PINS")
    require(pins.get("prepared_manifest") == prepared_snapshot.identity, "RUN_RESULT_PREPARED_PIN")
    require(pins.get("process_start_claim") == claim_snapshot.identity, "RUN_RESULT_CLAIM_PIN")
    require(pins.get("permanent_case_claim") == permanent_claim_snapshot.identity, "RUN_RESULT_PERMANENT_CLAIM_PIN")
    require(pins.get("permanent_case_reservation") == reservation_snapshot.identity, "RUN_RESULT_RESERVATION_PIN")
    integrity = result.get("integrity")
    require(isinstance(integrity, Mapping), "RUN_RESULT_INTEGRITY")
    require(integrity.get("case_spec_post") == BASE.identity(spec_path), "RUN_RESULT_SPEC_POST_PIN")
    require(integrity.get("runner_post") == dict(V2_RUNNER_IDENTITY), "RUN_RESULT_RUNNER_POST_PIN")
    return (
        result,
        result_snapshot,
        claim_snapshot,
        permanent_claim_snapshot,
        reservation_snapshot,
        prepared_snapshot,
    )


def _optional_regular_identity(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    return snapshot_regular(path, label).identity


def validate_zero_kf_watchdog_receipt(
    case_id: str,
    spec_path: Path,
    prepared: Mapping[str, Any],
    paths: Mapping[str, Path],
    result: Mapping[str, Any],
    result_snapshot: Snapshot,
    prepared_snapshot: Snapshot,
    stdout_snapshot: Snapshot,
) -> tuple[dict[str, Any], Snapshot, bool]:
    """Bind normal watchdog supervision; only a zero-signal passive run promotes."""

    receipt_path = watchdog_receipt_path(case_id)
    value, snapshot = read_canonical_json(receipt_path, "zero_kf_watchdog_receipt")
    require_exact_keys(
        value,
        (
            "schema_version",
            "status",
            "case_id",
            "started_at_utc",
            "ended_at_utc",
            "fixed_signature_grace_seconds",
            "signature_contract",
            "execution",
            "watchdog_action",
            "observations",
            "pins",
            "terminal_contract",
        ),
        "WATCHDOG_RECEIPT",
    )
    require(value.get("schema_version") == WATCHDOG_RECEIPT_SCHEMA, "WATCHDOG_RECEIPT_SCHEMA")
    require(value.get("case_id") == case_id, "WATCHDOG_RECEIPT_CASE")
    started_at = parse_canonical_utc_second(value.get("started_at_utc"), "WATCHDOG_STARTED")
    ended_at = parse_canonical_utc_second(value.get("ended_at_utc"), "WATCHDOG_ENDED")
    require(ended_at >= started_at, "WATCHDOG_TIME_ORDER")
    require(value.get("fixed_signature_grace_seconds") == 30.0, "WATCHDOG_GRACE_SECONDS")
    signature_contract = value.get("signature_contract")
    require(isinstance(signature_contract, Mapping), "WATCHDOG_SIGNATURE_CONTRACT_NOT_OBJECT")
    require(
        signature_contract
        == {
            "ordered_shutdown_before_saving": True,
            "complete_reported_atlas_map_id_set_required": True,
            "every_reported_atlas_map_zero_keyframes_required": True,
            "trajectory_must_remain_absent": str(paths["result_dir"] / "trajectory.txt"),
            "end_of_saving_must_remain_absent": True,
            "continuous_for_fixed_grace": True,
        },
        "WATCHDOG_SIGNATURE_CONTRACT",
    )
    status_value = value.get("status")
    require(
        status_value in (WATCHDOG_PASSIVE_STATUS, WATCHDOG_ZERO_KF_STATUS),
        "WATCHDOG_RECEIPT_NOT_NORMAL",
    )

    execution = value.get("execution")
    require(isinstance(execution, Mapping), "WATCHDOG_EXECUTION_NOT_OBJECT")
    require_exact_keys(
        execution,
        (
            "runner_entry",
            "runner_action",
            "case_spec",
            "authorization_transport",
            "authorization_token_in_os_argv",
            "authorization_token_in_environment",
            "authorization_token_serialized_in_receipt",
            "runner_popen_invocations",
            "hfnet_popen_authority_remains_with_frozen_runner",
            "retry_performed",
            "retry_permitted",
            "runner_returncode",
            "runner_reaped",
        ),
        "WATCHDOG_EXECUTION",
    )
    require(execution.get("runner_entry") == str(V2_RUNNER), "WATCHDOG_RUNNER_ENTRY")
    require(execution.get("runner_action") == "run", "WATCHDOG_RUNNER_ACTION")
    require(execution.get("case_spec") == str(spec_path), "WATCHDOG_CASE_SPEC_PATH")
    require(execution.get("runner_popen_invocations") == 1, "WATCHDOG_RUNNER_POPEN_COUNT")
    require(execution.get("runner_reaped") is True, "WATCHDOG_RUNNER_NOT_REAPED")
    expected_runner_returncode = (
        0
        if result.get("status") == "PASS_SAMEHISTORY_COLDSTART_RUNABILITY"
        else 2
    )
    require(
        execution.get("runner_returncode") == expected_runner_returncode,
        "WATCHDOG_RUNNER_RETURNCODE",
    )
    require(execution.get("retry_performed") is False, "WATCHDOG_RETRY_PERFORMED")
    require(execution.get("retry_permitted") is False, "WATCHDOG_RETRY_PERMITTED")
    require(
        execution.get("hfnet_popen_authority_remains_with_frozen_runner") is True,
        "WATCHDOG_HFNET_POPEN_AUTHORITY",
    )
    for key in (
        "authorization_token_in_os_argv",
        "authorization_token_in_environment",
        "authorization_token_serialized_in_receipt",
    ):
        require(execution.get(key) is False, f"WATCHDOG_AUTHORIZATION_LEAK_FLAG:{key}")
    require(
        execution.get("authorization_transport")
        == "ANONYMOUS_PIPE_TO_IN_MEMORY_RUNPY_ARGV",
        "WATCHDOG_AUTHORIZATION_TRANSPORT",
    )

    observations = value.get("observations")
    require(isinstance(observations, Mapping), "WATCHDOG_OBSERVATIONS_NOT_OBJECT")
    require_exact_keys(
        observations,
        (
            "child_discovered_at_utc",
            "exact_hfnet_child",
            "signature_first_observed_at_utc",
            "signature_evidence",
            "monitoring_errors",
        ),
        "WATCHDOG_OBSERVATIONS",
    )
    require(observations.get("monitoring_errors") == [], "WATCHDOG_MONITORING_ERRORS")
    child_discovered_at = parse_canonical_utc_second(
        observations.get("child_discovered_at_utc"), "WATCHDOG_CHILD_DISCOVERED"
    )
    require(started_at <= child_discovered_at <= ended_at, "WATCHDOG_CHILD_DISCOVERY_TIME_ORDER")
    child = observations.get("exact_hfnet_child")
    require(isinstance(child, Mapping), "WATCHDOG_EXACT_CHILD_MISSING")
    require_exact_keys(
        child,
        ("pid", "ppid", "starttime_ticks", "executable", "argv"),
        "WATCHDOG_EXACT_CHILD",
    )
    for key in ("pid", "ppid", "starttime_ticks"):
        require(
            isinstance(child.get(key), int)
            and not isinstance(child.get(key), bool)
            and child[key] > 0,
            f"WATCHDOG_EXACT_CHILD_IDENTITY:{key}",
        )
    require(
        child.get("executable") == os.path.realpath(str(prepared["stack"]["binary"]["path"])),
        "WATCHDOG_EXACT_CHILD_EXECUTABLE",
    )
    require(child.get("argv") == prepared["launch"]["argv"], "WATCHDOG_EXACT_CHILD_ARGV")
    signature = observations.get("signature_evidence")

    action = value.get("watchdog_action")
    require(isinstance(action, Mapping), "WATCHDOG_ACTION_NOT_OBJECT")
    require_exact_keys(
        action,
        (
            "sigterm_sent",
            "sigterm_sent_at_utc",
            "signal_attempt_count",
            "signal_count",
            "signal",
            "signal_scope",
            "process_group_signaled",
            "sigkill_sent",
            "other_process_signaled",
            "signal_delivery",
            "post_signal_identity_state",
        ),
        "WATCHDOG_ACTION",
    )
    require(action.get("process_group_signaled") is False, "WATCHDOG_PROCESS_GROUP_SIGNALLED")
    require(action.get("sigkill_sent") is False, "WATCHDOG_SIGKILL_SENT")
    require(action.get("other_process_signaled") is False, "WATCHDOG_OTHER_PROCESS_SIGNALLED")

    zero_kf_intervention = status_value == WATCHDOG_ZERO_KF_STATUS
    if zero_kf_intervention:
        require(action.get("sigterm_sent") is True, "WATCHDOG_ZERO_KF_SIGTERM_NOT_SENT")
        require(action.get("signal_attempt_count") == 1, "WATCHDOG_ZERO_KF_SIGNAL_ATTEMPTS")
        require(action.get("signal_count") == 1, "WATCHDOG_ZERO_KF_SIGNAL_COUNT")
        require(action.get("signal") == "SIGTERM", "WATCHDOG_ZERO_KF_SIGNAL")
        require(action.get("signal_scope") == "PIDFD_EXACT_CHILD_ONLY", "WATCHDOG_ZERO_KF_SIGNAL_SCOPE")
        sigterm_at = parse_canonical_utc_second(
            action.get("sigterm_sent_at_utc"), "WATCHDOG_SIGTERM_SENT"
        )
        require(started_at <= sigterm_at <= ended_at, "WATCHDOG_SIGTERM_TIME_ORDER")
        require(
            action.get("signal_delivery")
            == "SIGTERM_SENT_VIA_PIDFD_TO_EXACT_VALIDATED_HFNET_CHILD",
            "WATCHDOG_ZERO_KF_SIGNAL_DELIVERY",
        )
        require(
            action.get("post_signal_identity_state")
            in (
                "EXACT_CHILD_EXITED_OR_PROC_ENTRY_GONE_AFTER_SIGTERM",
                "SAME_EXACT_CHILD_STILL_OBSERVED_IMMEDIATELY_AFTER_SIGTERM",
                "PID_IDENTITY_CHANGED_AFTER_PIDFD_SIGTERM",
            ),
            "WATCHDOG_ZERO_KF_POST_SIGNAL_STATE",
        )
        require(isinstance(signature, Mapping), "WATCHDOG_ZERO_KF_SIGNATURE_MISSING")
        signature_first_at = parse_canonical_utc_second(
            observations.get("signature_first_observed_at_utc"),
            "WATCHDOG_SIGNATURE_FIRST_OBSERVED",
        )
        require(started_at <= signature_first_at <= sigterm_at, "WATCHDOG_SIGNATURE_TIME_ORDER")
        for key in (
            "confirmed",
            "shutdown_observed",
            "saving_trajectory_observed",
            "complete_atlas_rows_observed",
            "every_reported_atlas_map_zero_keyframes",
            "trajectory_absent",
            "end_of_saving_absent",
        ):
            require(signature.get(key) is True, f"WATCHDOG_ZERO_KF_SIGNATURE:{key}")
        require(
            isinstance(signature.get("atlas_map_count"), int)
            and signature["atlas_map_count"] >= 1,
            "WATCHDOG_ZERO_KF_ATLAS_COUNT",
        )
        rows = signature.get("map_keyframes_by_id")
        require(
            isinstance(rows, list)
            and rows == [[index, 0] for index in range(signature["atlas_map_count"])],
            "WATCHDOG_ZERO_KF_MAP_ROWS",
        )
    else:
        require(action.get("sigterm_sent") is False, "WATCHDOG_PASSIVE_SIGTERM_SENT")
        require(action.get("sigterm_sent_at_utc") is None, "WATCHDOG_PASSIVE_SIGTERM_TIME")
        require(action.get("signal_attempt_count") == 0, "WATCHDOG_PASSIVE_SIGNAL_ATTEMPTS")
        require(action.get("signal_count") == 0, "WATCHDOG_PASSIVE_SIGNAL_COUNT")
        require(action.get("signal") is None, "WATCHDOG_PASSIVE_SIGNAL")
        require(action.get("signal_scope") is None, "WATCHDOG_PASSIVE_SIGNAL_SCOPE")
        require(action.get("signal_delivery") is None, "WATCHDOG_PASSIVE_SIGNAL_DELIVERY")
        require(action.get("post_signal_identity_state") is None, "WATCHDOG_PASSIVE_POST_SIGNAL_STATE")
        require(signature is None, "WATCHDOG_PASSIVE_SIGNATURE_EVIDENCE")
        require(
            observations.get("signature_first_observed_at_utc") is None,
            "WATCHDOG_PASSIVE_SIGNATURE_TIME",
        )

    pins = value.get("pins")
    require(isinstance(pins, Mapping), "WATCHDOG_PINS_NOT_OBJECT")
    require_exact_keys(
        pins,
        (
            "supervisor_pre",
            "supervisor_post",
            "frozen_runner",
            "roster_pointer",
            "accuracy_prefreeze_seal",
            "case_spec",
            "prepared_manifest",
            "hfnet_binary",
            "stdout_log_at_receipt",
            "trajectory_at_receipt",
            "runner_result_at_receipt",
        ),
        "WATCHDOG_PINS",
    )
    require(pins.get("supervisor_pre") == dict(WATCHDOG_IDENTITY), "WATCHDOG_SUPERVISOR_PRE_PIN")
    require(pins.get("supervisor_post") == dict(WATCHDOG_IDENTITY), "WATCHDOG_SUPERVISOR_POST_PIN")
    require(pins.get("frozen_runner") == dict(V2_RUNNER_IDENTITY), "WATCHDOG_RUNNER_PIN")
    require(pins.get("case_spec") == BASE.identity(spec_path), "WATCHDOG_CASE_SPEC_PIN")
    require(pins.get("prepared_manifest") == prepared_snapshot.identity, "WATCHDOG_PREPARED_PIN")
    require(pins.get("hfnet_binary") == prepared["stack"]["binary"], "WATCHDOG_BINARY_PIN")
    require(pins.get("stdout_log_at_receipt") == stdout_snapshot.identity, "WATCHDOG_STDOUT_PIN")
    require(
        pins.get("trajectory_at_receipt")
        == _optional_regular_identity(paths["result_dir"] / "trajectory.txt", "watchdog_trajectory"),
        "WATCHDOG_TRAJECTORY_PIN",
    )
    require(pins.get("runner_result_at_receipt") == result_snapshot.identity, "WATCHDOG_RESULT_PIN")
    for key, expected_path in (
        (
            "roster_pointer",
            WATCHDOG_ROSTER_POINTER,
        ),
        (
            "accuracy_prefreeze_seal",
            WATCHDOG_ACCURACY_PREFREEZE_SEAL,
        ),
    ):
        expected = pins.get(key)
        require(isinstance(expected, Mapping), f"WATCHDOG_AUTHORITY_PIN:{key}")
        require(str(expected.get("path")) == str(expected_path), f"WATCHDOG_AUTHORITY_PATH:{key}")
        require_identity(snapshot_regular(expected_path, f"watchdog_{key}"), expected, f"watchdog_{key}")

    terminal = value.get("terminal_contract")
    require(isinstance(terminal, Mapping), "WATCHDOG_TERMINAL_NOT_OBJECT")
    require_exact_keys(
        terminal,
        (
            "receipt_path",
            "receipt_outside_attempt_directory",
            "receipt_publication",
            "watchdog_retry_after_receipt",
            "watchdog_never_fabricates_or_edits_runner_outputs",
        ),
        "WATCHDOG_TERMINAL",
    )
    require(terminal.get("receipt_path") == str(receipt_path), "WATCHDOG_TERMINAL_RECEIPT_PATH")
    require(terminal.get("receipt_outside_attempt_directory") is True, "WATCHDOG_RECEIPT_LOCATION")
    require(
        terminal.get("receipt_publication")
        == "TEMP_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC",
        "WATCHDOG_RECEIPT_PUBLICATION",
    )
    require(terminal.get("watchdog_retry_after_receipt") is False, "WATCHDOG_TERMINAL_RETRY")
    require(
        terminal.get("watchdog_never_fabricates_or_edits_runner_outputs") is True,
        "WATCHDOG_OUTPUT_MUTATION_POLICY",
    )

    signature_is_zero_kf = isinstance(signature, Mapping) and signature.get("confirmed") is True
    promotable_passive = bool(
        status_value == WATCHDOG_PASSIVE_STATUS
        and not zero_kf_intervention
        and not signature_is_zero_kf
        and action.get("signal_attempt_count") == 0
        and action.get("signal_count") == 0
        and result.get("execution", {}).get("raw_returncode") == 0
    )
    return (
        {
            "status": status_value,
            "promotable_passive": promotable_passive,
            "zero_kf_intervention": zero_kf_intervention,
            "confirmed_zero_kf_signature": signature_is_zero_kf,
            "runner_reaped": True,
            "monitoring_errors": [],
            "signal_attempt_count": action.get("signal_attempt_count"),
            "signal_count": action.get("signal_count"),
            "raw_runability_receipt_pin": pins.get("runner_result_at_receipt"),
        },
        snapshot,
        promotable_passive,
    )


def validate_post(spec_path: Path) -> dict[str, Any]:
    spec, prepared, immutable, paths = immutable_prepared_contract(
        spec_path, require_cache_seed=False
    )
    case_id = _case_id(spec)
    prestart, prestart_snapshot = _verify_prestart_receipt(case_id)
    require(
        prestart.get("immutable_prepared_contract") == immutable,
        "IMMUTABLE_CONTRACT_CHANGED_SINCE_PRESTART",
    )
    pre_model = prestart.get("model_directory")
    require(isinstance(pre_model, Mapping), "PRESTART_MODEL_DIRECTORY_EVIDENCE")
    post_model = audit_model_directory(
        paths["local_model"],
        paths["local_cache"],
        Path(str(prepared["stack"]["shared_cache"]["path"])),
        prepared["derived"]["local_onnx"],
        prepared["stack"]["shared_cache"],
        require_seed=False,
    )
    require(
        post_model["local_onnx"] == pre_model.get("local_onnx"),
        "LOCAL_ONNX_CHANGED_SINCE_PRESTART",
    )
    require(
        post_model["shared_cache_seed"] == pre_model.get("shared_cache_seed"),
        "SHARED_CACHE_CHANGED_SINCE_PRESTART",
    )
    require_local_cache_in_place(pre_model, post_model)
    (
        result,
        result_snapshot,
        claim_snapshot,
        permanent_claim_snapshot,
        reservation_snapshot,
        prepared_snapshot,
    ) = _validate_runner_receipts(case_id, spec_path, prepared, paths)
    stdout_snapshot = snapshot_regular(paths["stdout"], "stdout")
    stderr_snapshot = snapshot_regular(paths["stderr"], "stderr")
    require(result["pins"].get("stdout") == stdout_snapshot.identity, "RUN_RESULT_STDOUT_PIN")
    require(result["pins"].get("stderr") == stderr_snapshot.identity, "RUN_RESULT_STDERR_PIN")
    watchdog, watchdog_snapshot, watchdog_promotable = validate_zero_kf_watchdog_receipt(
        case_id,
        spec_path,
        prepared,
        paths,
        result,
        result_snapshot,
        prepared_snapshot,
        stdout_snapshot,
    )
    timing = audit_timing_cache_events(
        paths["stderr"].read_bytes(),
        paths["stdout"].read_bytes(),
        paths["local_cache"],
        int(pre_model["local_cache"]["identity"]["size_bytes"]),
        int(post_model["local_cache"]["identity"]["size_bytes"]),
    )
    cache_changed = (
        post_model["local_cache"]["identity"]
        != pre_model["local_cache"]["identity"]
    )
    retained, carved, cache_only = derive_failure_codes(
        result.get("failure_codes", []),
        result.get("post_audit_errors", []),
        cache_changed=cache_changed,
    )
    scientific = independent_scientific_runability_audit(spec, paths, result)
    if cache_only:
        integrity = result["integrity"]
        require(integrity.get("frozen_contract_unchanged") is False, "CACHE_ERROR_INTEGRITY_FLAG")
        require(integrity.get("post_contract") is None, "CACHE_ERROR_POST_CONTRACT_NOT_NULL")
    exact_promotable_incident = bool(
        result.get("status") == "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"
        and set(result.get("failure_codes", [])) == set(CACHE_CONSEQUENT_FAILURE_CODES)
        and len(result.get("failure_codes", [])) == len(CACHE_CONSEQUENT_FAILURE_CODES)
        and result.get("post_audit_errors") == [EXPECTED_CACHE_POST_ERROR]
        and cache_only
        and not retained
        and scientific["status"] == "PASS"
        and scientific["failure_codes"] == []
        and watchdog_promotable
    )
    status = "PASS" if exact_promotable_incident else "FAIL"
    if not exact_promotable_incident:
        retained = list(dict.fromkeys([*retained, *scientific["failure_codes"]]))
        if not watchdog_promotable:
            retained = list(dict.fromkeys([*retained, "WATCHDOG_NOT_PROMOTABLE_PASSIVE"]))
        if not retained:
            retained = ["RAW_INCIDENT_NOT_EXACT_CACHE_ONLY_PROMOTABLE_SET"]
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "status": status,
        "role": "INDEPENDENT_CACHE_VALIDATOR_ADJUDICATION",
        "effective_runability_status": status,
        "adjudication_status": (
            "PASS_CACHE_ONLY_V2_POST_AUDIT_CORRECTED"
            if status == "PASS"
            else "FAIL_RUNABILITY_AFTER_CACHE_CONTRACT_ADJUDICATION"
        ),
        "case_id": case_id,
        "validator": snapshot_regular(VALIDATOR, "validator_self").identity,
        "failure_codes": retained,
        "support": scientific["support"],
        "support_trajectory_identity": scientific["support"]["trajectory"].get(
            "identity"
        ),
        "independent_scientific_runability_audit": scientific,
        "execution": result.get("execution"),
        "accuracy_computed": False,
        "raw_runability_receipt": result_snapshot.identity,
        "prestart_receipt": prestart_snapshot.identity,
        "zero_kf_watchdog_receipt": watchdog_snapshot.identity,
        "cache_contract_delta_seal": dict(ADDENDUM_IDENTITY),
        "accuracy_authority_supersession": prestart[
            "accuracy_authority_supersession"
        ],
        "terminal_contract": {
            "attempt_consumed": True,
            "retry_after_pass_or_fail": False,
            "claim_without_result_is_terminal_fail": True,
            "replacement_adjudication_permitted": False,
        },
        "cache_contract": {
            "prestart_receipt": prestart_snapshot.identity,
            "prestart_seed": pre_model["local_cache"],
            "post_cache": post_model["local_cache"],
            "cache_changed": cache_changed,
            "cache_only_v2_post_audit_error_proven": cache_only,
            "exact_promotable_raw_incident_proven": exact_promotable_incident,
            "raw_runner_failure_codes": result.get("failure_codes", []),
            "raw_runner_post_audit_errors": result.get("post_audit_errors", []),
            "carved_consequent_failure_codes": carved,
            "timing_cache_events": timing,
            "model_directory_post": post_model,
            "zero_kf_watchdog": watchdog,
        },
        "immutable_contract": immutable,
        "pins": {
            "validator": snapshot_regular(VALIDATOR, "validator_self").identity,
            "governance_addendum": dict(ADDENDUM_IDENTITY),
            "accuracy_authority_supersession": prestart[
                "accuracy_authority_supersession"
            ],
            "v2_runner": dict(V2_RUNNER_IDENTITY),
            "v2_run_result": result_snapshot.identity,
            "prepared_manifest": prepared_snapshot.identity,
            "attempt_process_claim": claim_snapshot.identity,
            "permanent_process_claim": permanent_claim_snapshot.identity,
            "permanent_start_reservation": reservation_snapshot.identity,
            "stdout": stdout_snapshot.identity,
            "stderr": stderr_snapshot.identity,
            "zero_kf_watchdog_receipt": watchdog_snapshot.identity,
        },
        "claim_boundary": {
            "accuracy_evaluated": False,
            "ranking_authorized": False,
            "published_accuracy_seal_accepts_this_receipt": False,
            "future_accuracy_authority_must_explicitly_adopt_receipt": True,
            "a05_retroactive_adjudication_permitted": False,
        },
    }


def _error_code(error: BaseException) -> str:
    if isinstance(error, ContractError):
        return str(error)
    return f"{type(error).__name__}:{error}"


def publish_post(spec_path: Path) -> dict[str, Any]:
    # Validate the spec/case before permitting a permanent failure receipt.
    spec, _identity = BASE.validate_spec(spec_path, require_attempt_absent=False)
    case_id = _case_id(spec)
    destination = adjudication_receipt_path(case_id)
    with BASE.global_serial_lock() as lock:
        _require_absent(destination, "post_adjudication")
        try:
            value = validate_post(spec_path)
            # Immediate pre-publication TOCTOU revalidation.
            second = validate_post(spec_path)
            require(value == second, "POST_ADJUDICATION_TOCTOU_DRIFT")
        except BaseException as error:
            value = {
                "schema_version": ADJUDICATION_SCHEMA,
                "status": "FAIL",
                "role": "INDEPENDENT_CACHE_VALIDATOR_ADJUDICATION",
                "effective_runability_status": "FAIL",
                "adjudication_status": "FAIL_CACHE_CONTRACT_VALIDATION",
                "case_id": case_id,
                "failure_codes": [f"CACHE_CONTRACT_VALIDATION:{_error_code(error)}"],
                "accuracy_computed": False,
                "cache_contract_delta_seal": dict(ADDENDUM_IDENTITY),
                "terminal_contract": {
                    "attempt_consumed": True,
                    "retry_after_pass_or_fail": False,
                    "claim_without_result_is_terminal_fail": True,
                    "replacement_adjudication_permitted": False,
                },
                "pins": {
                    "validator": snapshot_regular(VALIDATOR, "validator_self").identity,
                    "governance_addendum": dict(ADDENDUM_IDENTITY),
                    "v2_runner": dict(V2_RUNNER_IDENTITY),
                },
                "claim_boundary": {
                    "accuracy_evaluated": False,
                    "ranking_authorized": False,
                    "published_accuracy_seal_accepts_this_receipt": False,
                    "future_accuracy_authority_must_explicitly_adopt_receipt": True,
                    "a05_retroactive_adjudication_permitted": False,
                },
            }
        value = {**value, "adjudicated_at_utc": BASE.now_utc(), "roster_global_lock": lock}
        published = atomic_publish_noreplace(destination, value)
    return {**value, "receipt_identity": published.identity}


def validate_published_adjudication(spec_path: Path) -> dict[str, Any]:
    """Recompute a canonical PASS receipt while validating its two publish fields."""

    spec, _identity = BASE.validate_spec(spec_path, require_attempt_absent=False)
    case_id = _case_id(spec)
    value, snapshot = read_canonical_json(
        adjudication_receipt_path(case_id), "published_cache_adjudication"
    )
    require(value.get("schema_version") == ADJUDICATION_SCHEMA, "PUBLISHED_ADJUDICATION_SCHEMA")
    require(value.get("status") == "PASS", "PUBLISHED_ADJUDICATION_NOT_PASS")
    require(value.get("case_id") == case_id, "PUBLISHED_ADJUDICATION_CASE")
    adjudicated_at = parse_canonical_utc_second(
        value.get("adjudicated_at_utc"), "PUBLISHED_ADJUDICATED_AT"
    )
    lock = value.get("roster_global_lock")
    require(isinstance(lock, Mapping), "PUBLISHED_ADJUDICATION_LOCK_NOT_OBJECT")
    require_exact_keys(
        lock, ("path", "pid", "acquired_at_utc"), "PUBLISHED_ADJUDICATION_LOCK"
    )
    require(lock.get("path") == str(BASE.global_lock_path()), "PUBLISHED_ADJUDICATION_LOCK_PATH")
    require(
        isinstance(lock.get("pid"), int)
        and not isinstance(lock.get("pid"), bool)
        and lock["pid"] > 0,
        "PUBLISHED_ADJUDICATION_LOCK_PID",
    )
    acquired_at = parse_canonical_utc_second(
        lock.get("acquired_at_utc"), "PUBLISHED_ADJUDICATION_LOCK_ACQUIRED"
    )
    require(acquired_at <= adjudicated_at, "PUBLISHED_ADJUDICATION_TIME_ORDER")
    projection = dict(value)
    del projection["adjudicated_at_utc"]
    del projection["roster_global_lock"]
    recomputed = validate_post(spec_path)
    require(projection == recomputed, "PUBLISHED_ADJUDICATION_NOT_EXACT_RECOMPUTATION")
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "status": "PASS_PUBLISHED_ADJUDICATION_EXACTLY_RECOMPUTED",
        "case_id": case_id,
        "receipt_identity": snapshot.identity,
        "validator": snapshot_regular(VALIDATOR, "validator_self").identity,
        "raw_runability_receipt": value["raw_runability_receipt"],
        "prestart_receipt": value["prestart_receipt"],
        "zero_kf_watchdog_receipt": value["zero_kf_watchdog_receipt"],
        "accuracy_authority_supersession": value["accuracy_authority_supersession"],
        "accuracy_computed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "check-prestart",
            "freeze-prestart",
            "check-post",
            "publish-post",
            "verify-published-post",
        ),
    )
    parser.add_argument("--case-spec", type=Path, required=True)
    parser.add_argument("--authorization-token", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.action == "check-prestart":
            result = validate_prestart(arguments.case_spec)
        elif arguments.action == "freeze-prestart":
            require(
                secrets.compare_digest(arguments.authorization_token, FREEZE_TOKEN),
                "FREEZE_AUTHORIZATION_TOKEN",
            )
            result = freeze_prestart(arguments.case_spec)
        elif arguments.action == "check-post":
            result = validate_post(arguments.case_spec)
        elif arguments.action == "verify-published-post":
            result = validate_published_adjudication(arguments.case_spec)
        else:
            require(
                secrets.compare_digest(arguments.authorization_token, PUBLISH_TOKEN),
                "PUBLISH_AUTHORIZATION_TOKEN",
            )
            result = publish_post(arguments.case_spec)
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0 if result.get("status") not in ("FAIL",) else 1
    except BaseException as error:
        sys.stdout.buffer.write(
            canonical_json_bytes(
                {
                    "schema_version": ADJUDICATION_SCHEMA,
                    "status": "BLOCKED_NO_ADJUDICATION",
                    "error": _error_code(error),
                    "case_started": False,
                    "files_published": False,
                    "accuracy_evaluated": False,
                    "ranking_authorized": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
