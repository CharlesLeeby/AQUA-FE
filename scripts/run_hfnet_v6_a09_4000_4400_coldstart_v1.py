#!/usr/bin/env python3
"""One-shot HFNet-SLAM run on the canonical A09 4000..4400 cold-start input.

The exercised A10 supervisor is reused without changing its terminal artifact.
This profile replaces every input, attempt, timestamp, authority, and scientific
label before prepare/check/run.  It is intentionally development-only and
permits one process start and no retry.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_hfnet_v6_a10_2400_2800_coldstart_v1 as profile


RUNNER = Path(__file__).resolve()
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a09_4000_4400_coldstart"
)
INPUT_MANIFEST = INPUT_ROOT / "materialization_manifest.json"
INPUT_AUDIT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a09_4000_4400_coldstart.audit.json"
)
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a09_4000_4400_coldstart/attempt_001"
)
SOURCE_FIRST = 4000
SOURCE_LAST = 4400
CAMERA_COUNT = 401
FIRST_NS = 1542888946038630384
LAST_NS = 1542888966034698672
TIMES_SIZE = 8020
TIMES_SHA256 = "f73f70dd4b5fe145665140dd38a0427229295661d215ce26958953867aa4fce9"
INPUT_PAYLOAD_SHA256 = "552c3865562d8135037135971e4a24d7776492d608e2bd42b957de74e94f6c08"
INPUT_MANIFEST_SHA256 = "c572d90d3c5f9be00902cd4eb804e0afc90252002bdd212a9a6ee63a1c2f696d"
INPUT_AUDIT_SHA256 = "bfa635a6d96142a87f2ccc4160df18916c0f97fda78e130a64b8395698b65f30"
AUTHORIZATION_TOKEN = "HFNET_V6_A09_4000_4400_COLDSTART_ATTEMPT_001_START_EXACTLY_ONCE"
SCHEMA = "aqua-fe-hfnet-v6-a09-4000-4400-coldstart-result-v1"
INHERITED_SUPERVISOR = ROOT / "scripts/run_hfnet_v6_a10_2400_2800_coldstart_v1.py"
INHERITED_SUPERVISOR_SIZE = 17469
INHERITED_SUPERVISOR_SHA256 = "3d940446493bd36cf9cbe590a643142eae1452df5759a5409b344ca3f9cf2c0e"
INHERITED_BASE = ROOT / "scripts/run_hfnet_v6_a06_2210_2460_coldstart_v1.py"
INHERITED_BASE_SIZE = 22647
INHERITED_BASE_SHA256 = "e155e21018fd8cfbc3c2331f07d9542f5e8f398b63dec0096ea450a55e22d8c9"
_BOUND_POPEN_COUNT = 0


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_4000_4400.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_code_authority() -> None:
    rows = (
        (
            "A10_SUPERVISOR",
            INHERITED_SUPERVISOR,
            Path(profile.__file__).resolve(),
            INHERITED_SUPERVISOR_SIZE,
            INHERITED_SUPERVISOR_SHA256,
        ),
        (
            "A06_BASE",
            INHERITED_BASE,
            Path(profile.base.__file__).resolve(),
            INHERITED_BASE_SIZE,
            INHERITED_BASE_SHA256,
        ),
    )
    for label, expected_path, imported_path, expected_size, expected_sha in rows:
        if imported_path != expected_path or expected_path.is_symlink() or not expected_path.is_file():
            raise profile.base.ContractError(f"{label}_PATH_OR_TYPE_MISMATCH")
        if expected_path.stat().st_size != expected_size or _sha256(expected_path) != expected_sha:
            raise profile.base.ContractError(f"{label}_IDENTITY_MISMATCH")


def validate_input_authority() -> dict[str, Any]:
    """Recheck every canonical file immediately before process authorization."""
    validate_code_authority()
    if INPUT_ROOT.is_symlink() or not INPUT_ROOT.is_dir():
        raise profile.base.ContractError("A09_INPUT_ROOT_MISSING_OR_SYMLINK")
    if not INPUT_MANIFEST.is_file() or INPUT_MANIFEST.is_symlink():
        raise profile.base.ContractError("A09_INPUT_MANIFEST_MISSING")
    if _sha256(INPUT_MANIFEST) != INPUT_MANIFEST_SHA256:
        raise profile.base.ContractError("A09_INPUT_MANIFEST_IDENTITY_MISMATCH")
    if not INPUT_AUDIT.is_file() or INPUT_AUDIT.is_symlink():
        raise profile.base.ContractError("A09_INDEPENDENT_AUDIT_RECEIPT_MISSING")
    if _sha256(INPUT_AUDIT) != INPUT_AUDIT_SHA256:
        raise profile.base.ContractError("A09_INDEPENDENT_AUDIT_IDENTITY_MISMATCH")

    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(INPUT_AUDIT.read_text(encoding="utf-8"))
    selection = manifest.get("selection", {})
    payload = manifest.get("payload_identity_excluding_manifest", {})
    if (
        manifest.get("status") != "PASS_PREPARATION_ONLY"
        or selection.get("sequence_id") != "A09"
        or selection.get("camera_indices_inclusive") != [SOURCE_FIRST, SOURCE_LAST]
        or selection.get("cold_start") is not True
        or payload.get("sha256") != INPUT_PAYLOAD_SHA256
    ):
        raise profile.base.ContractError("A09_INPUT_MANIFEST_CONTRACT_MISMATCH")

    independent = audit.get("independent_audit", {})
    audited_manifest = independent.get("manifest", {})
    if (
        audit.get("status")
        != "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_PREPARATION_ONLY"
        or independent.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        or independent.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or audit.get("materialization", {})
        .get("payload_identity_excluding_manifest", {})
        .get("sha256")
        != INPUT_PAYLOAD_SHA256
        or audited_manifest.get("sha256") != INPUT_MANIFEST_SHA256
        or audited_manifest.get("size_bytes") != INPUT_MANIFEST.stat().st_size
    ):
        raise profile.base.ContractError("A09_AUDIT_TO_MANIFEST_BINDING_MISMATCH")

    expected_files: set[str] = {"materialization_manifest.json"}
    camera_files = manifest.get("camera", {}).get("files", [])
    if len(camera_files) != CAMERA_COUNT:
        raise profile.base.ContractError("A09_MANIFEST_CAMERA_FILE_COUNT_MISMATCH")
    for row in camera_files:
        relative = row.get("path")
        if not isinstance(relative, str):
            raise profile.base.ContractError("A09_MANIFEST_CAMERA_PATH_INVALID")
        expected_files.add(relative)
        observed = profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise profile.base.ContractError(f"A09_CAMERA_FILE_DRIFT:{relative}")

    generated_paths = {
        "cam0_times": "cam0_times.txt",
        "cam0_data_csv": "mav0/cam0/data.csv",
        "imu0_data_csv": "mav0/imu0/data.csv",
    }
    generated = manifest.get("generated_files", {})
    for key, relative in generated_paths.items():
        row = generated.get(key, {})
        expected_files.add(relative)
        observed = profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise profile.base.ContractError(f"A09_GENERATED_FILE_DRIFT:{relative}")

    tree = list(INPUT_ROOT.rglob("*"))
    observed_files = {
        path.relative_to(INPUT_ROOT).as_posix()
        for path in tree
        if path.is_file() and not path.is_symlink()
    }
    if observed_files != expected_files or any(path.is_symlink() for path in tree):
        raise profile.base.ContractError("A09_INPUT_FILE_SET_OR_SYMLINK_DRIFT")
    return manifest


def selected_timestamps() -> list[int]:
    validate_input_authority()
    time_path = INPUT_ROOT / "cam0_times.txt"
    if time_path.stat().st_size != TIMES_SIZE or _sha256(time_path) != TIMES_SHA256:
        raise profile.base.ContractError("A09_TIMES_IDENTITY_MISMATCH")
    try:
        stamps = [int(row) for row in time_path.read_text(encoding="ascii").splitlines()]
    except ValueError as error:
        raise profile.base.ContractError("A09_TIMESTAMPS_NOT_INTEGER") from error
    if len(stamps) != CAMERA_COUNT or stamps[0] != FIRST_NS or stamps[-1] != LAST_NS:
        raise profile.base.ContractError("A09_TIMESTAMP_BOUNDARY_MISMATCH")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise profile.base.ContractError("A09_TIMESTAMPS_NOT_STRICT")
    return stamps


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    """Finalize A09 labels before the sole atomic publication."""
    if path == profile.paths()["prepared"] and isinstance(value, dict):
        value["schema_version"] = "aqua-fe-hfnet-v6-a09-4000-4400-coldstart-prepared-v1"
        value["scientific_role"] = (
            "DEVELOPMENT_ONLY_EXTERNAL_LEARNED_WHOLE_SYSTEM_ON_A09_"
            "LEARNED_ACTIVE_POSITIVE_WINDOW"
        )
        value["selection"] = {
            "sequence": "AQUALOC archaeology_sequence_09",
            "source_frame_indices_inclusive": [SOURCE_FIRST, SOURCE_LAST],
            "camera_count": CAMERA_COUNT,
            "camera_header_ns_inclusive": [FIRST_NS, LAST_NS],
            "span_seconds": (LAST_NS - FIRST_NS) / 1e9,
            "history": "cold_start_at_source_frame_4000; no frame before 4000 passed to HFNet",
            "development_result_conditioned_selection": True,
            "prior_project_result": (
                "AQUA-FE active final-online beat KLT in 5/5 development replays "
                "with 30 injected observations"
            ),
        }
        value["input_authority"] = {
            "materialization_manifest": profile.base.identity(INPUT_MANIFEST),
            "independent_audit_receipt": profile.base.identity(INPUT_AUDIT),
            "payload_sha256_excluding_manifest": INPUT_PAYLOAD_SHA256,
        }
        value["controller_authority"] = {
            "inherited_a10_supervisor": profile.base.identity(INHERITED_SUPERVISOR),
            "inherited_a06_base": profile.base.identity(INHERITED_BASE),
        }
    elif path == profile.paths()["claim"] and isinstance(value, dict):
        value = dict(value)
        value["schema_version"] = "aqua-fe-hfnet-v6-a09-4000-4400-coldstart-claim-v1"
    elif path == profile.paths()["result"] and isinstance(value, dict):
        value["schema_version"] = SCHEMA
        value["watchdog"] = dict(profile._ACTIVE_WATCHDOG or {"triggered": False})
        if profile._ACTIVE_WATCHDOG and profile._ACTIVE_WATCHDOG.get("triggered") is True:
            value["status"] = "FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES"
            value["failure_code"] = profile._ACTIVE_WATCHDOG.get("failure_code")
            value["execution"]["termination"] = (
                "FROZEN_ALL_MAPS_ZERO_KEYFRAME_SAVE_HANG_WATCHDOG_SIGTERM"
            )
    terminal_paths = {
        profile.paths()["prepared"],
        profile.paths()["claim"],
        profile.paths()["result"],
    }
    profile._BASE_ATOMIC_JSON(path, value, exclusive=exclusive or path in terminal_paths)


def bound_popen(*args: object, **kwargs: object):
    """Allow frozen read-only GPU probes, then one exact HFNet child."""
    global _BOUND_POPEN_COUNT
    expected_argv = [
        str(profile.base.BINARY),
        str(paths()["runtime_config"]),
        str(paths()["result_dir"]) + "/",
        str(INPUT_ROOT),
        str(paths()["subset_times"]),
    ]
    argv = args[0] if len(args) == 1 and "args" not in kwargs else kwargs.get("args")
    diagnostic_argv = {
        (
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ),
        (
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ),
    }
    if isinstance(argv, (list, tuple)) and tuple(argv) in diagnostic_argv:
        return profile._ORIGINAL_POPEN(*args, **kwargs)
    expected_keyword_set = {"cwd", "env", "stdout", "stderr", "start_new_session"}
    stdout = kwargs.get("stdout")
    stderr = kwargs.get("stderr")
    contract_ok = (
        isinstance(argv, (list, tuple))
        and list(argv) == expected_argv
        and set(kwargs) == expected_keyword_set
        and kwargs.get("cwd") == str(ATTEMPT)
        and kwargs.get("env") == profile.base.runtime_environment()
        and getattr(stdout, "name", None) == str(paths()["stdout"])
        and getattr(stderr, "name", None) == str(paths()["stderr"])
        and kwargs.get("start_new_session") is True
        and _BOUND_POPEN_COUNT == 0
    )
    if not contract_ok:
        raise profile.base.ContractError("A09_ONLY_POPEN_EXACT_LAUNCH_CONTRACT_MISMATCH")
    _BOUND_POPEN_COUNT += 1
    process = profile._ORIGINAL_POPEN(*args, **kwargs)
    if profile._ACTIVE_WATCHDOG is not None:
        profile._ACTIVE_WATCHDOG["pid"] = process.pid
    if profile._CHILD_READY is not None:
        profile._CHILD_READY.set()
    return process


def configure_profile() -> None:
    validate_code_authority()
    profile.RUNNER = RUNNER
    profile.INPUT_ROOT = INPUT_ROOT
    profile.INPUT_MANIFEST = INPUT_MANIFEST
    profile.INPUT_AUDIT = INPUT_AUDIT
    profile.ATTEMPT = ATTEMPT
    profile.SOURCE_FIRST = SOURCE_FIRST
    profile.SOURCE_LAST = SOURCE_LAST
    profile.CAMERA_COUNT = CAMERA_COUNT
    profile.FIRST_NS = FIRST_NS
    profile.LAST_NS = LAST_NS
    profile.TIMES_SIZE = TIMES_SIZE
    profile.TIMES_SHA256 = TIMES_SHA256
    profile.INPUT_PAYLOAD_SHA256 = INPUT_PAYLOAD_SHA256
    profile.INPUT_MANIFEST_SHA256 = INPUT_MANIFEST_SHA256
    profile.INPUT_AUDIT_SHA256 = INPUT_AUDIT_SHA256
    profile.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    profile.SCHEMA = SCHEMA
    profile.paths = paths
    profile.validate_input_authority = validate_input_authority
    profile.selected_timestamps = selected_timestamps
    profile.profile_atomic_json = profile_atomic_json
    profile.bound_popen = bound_popen
    profile.check = check


def check() -> dict[str, object]:
    profile.configure_base()
    value = profile.base.check(require_unclaimed=True)
    value["schema_version"] = "aqua-fe-hfnet-v6-a09-4000-4400-coldstart-check-v1"
    return value


def main() -> int:
    configure_profile()
    return profile.main()


if __name__ == "__main__":
    raise SystemExit(main())
