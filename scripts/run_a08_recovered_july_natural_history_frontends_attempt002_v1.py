#!/usr/bin/env python3
"""Additive ROS-seeded attempt 002 for the frozen A08 frontend runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
BASE_RUNNER = WORKSPACE / "scripts/run_a08_recovered_july_natural_history_frontends_v1.py"
AMENDMENT = (
    WORKSPACE
    / "papers/a08_recovered_july_frontend_attempt002_infrastructure_amendment_v1.md"
)

SPEC = importlib.util.spec_from_file_location("a08_frontend_attempt001_frozen", BASE_RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("BASE_RUNNER_IMPORT_SPEC")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

ORIGINAL_ENVIRONMENT_UPDATES = BASE.environment_updates
ORIGINAL_ENVIRONMENT_FINGERPRINT = BASE.environment_fingerprint
ORIGINAL_FIXED_INPUTS = BASE.fixed_inputs
ORIGINAL_WRITE_EXCLUSIVE = BASE.write_exclusive

ATTEMPT1_IDENTITIES = {
    BASE_RUNNER: (
        48_196,
        "9ce1bcd18db77821a86c090381174316ac84a77dafe0842c0a1bb6d6eafea900",
    ),
    AMENDMENT: (
        2_910,
        "faba3c35a85b372da5b9c813510228e2815e063995245c70f0333b7e695d172d",
    ),
    BASE.FRONTEND_ROOT / "klt_process_start_claim_v1.json": (
        123_991,
        "d87c9e33a508003a76939d04e132cb293a383ffb77bf9ae7cefe423ebdb6b22d",
    ),
    BASE.FRONTEND_ROOT / "klt_supervisor_process.log": (
        91,
        "86545b23ad558c32d40807734e556cac85727a62f69640198be653b738f93d22",
    ),
    BASE.FRONTEND_ROOT / "klt_export_failure_v1.json": (
        837,
        "6801f0db2b5cb409648588a0dc01dc31c383732699ecc645a61c174d0e249e37",
    ),
}
ATTEMPT1_RUN = (
    BASE.RUN_ROOT
    / "external_klt_every2_a08_recoveredjuly_hist0000_4660_klt_export_v1"
)


def environment_updates() -> dict[str, str]:
    """Return the complete sealed environment with canonical ROS seed values."""
    value = ORIGINAL_ENVIRONMENT_UPDATES()
    value.update(
        {
            "ROS_DISTRO": "noetic",
            "ROS_MASTER_URI": "http://localhost:11311",
        }
    )
    return value


def source_chain_identity(paths: list[str]) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for raw_prefix in paths:
        prefix = Path(raw_prefix)
        BASE.require(prefix.is_dir() and not prefix.is_symlink(), f"SETUP_PREFIX:{prefix}")
        candidates = [
            prefix / ".catkin",
            prefix / "_setup_util.py",
            prefix / "setup.bash",
            prefix / "setup.sh",
            prefix / "local_setup.bash",
            prefix / "local_setup.sh",
        ]
        hook_root = prefix / "etc/catkin/profile.d"
        if hook_root.is_dir() and not hook_root.is_symlink():
            candidates.extend(
                path for path in sorted(hook_root.rglob("*")) if path.is_file()
            )
        for candidate in candidates:
            if not candidate.exists():
                continue
            resolved = candidate.resolve()
            BASE.require(resolved.is_file(), f"SETUP_NONREGULAR:{candidate}")
            identities[str(candidate)] = BASE.identity(resolved)
    BASE.require(identities, "SETUP_CLOSURE_EMPTY")
    return dict(sorted(identities.items()))


EXPECTED_HOOK_PATHS = [
    "/opt/ros/noetic/etc/catkin/profile.d/1.ros_distro.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/1.ros_etc_dir.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/1.ros_package_path.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/1.ros_python_version.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/1.ros_version.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/10.rosbuild.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/10.roslaunch.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/99.roslisp.sh",
    "/opt/ros/noetic/etc/catkin/profile.d/05.catkin_make.bash",
    "/opt/ros/noetic/etc/catkin/profile.d/05.catkin_make_isolated.bash",
    "/opt/ros/noetic/etc/catkin/profile.d/15.rosbash.bash",
    "/opt/ros/noetic/etc/catkin/profile.d/20.transform.bash",
]


def exact_sourced_closure() -> dict[str, dict[str, Any]]:
    paths = [
        Path("/opt/ros/noetic/.catkin"),
        Path("/opt/ros/noetic/_setup_util.py"),
        Path("/opt/ros/noetic/setup.bash"),
        Path("/opt/ros/noetic/setup.sh"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/.catkin"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/_setup_util.py"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.sh"),
        Path("/home/ma/dave_ws/devel/.catkin"),
        Path("/home/ma/uuv_ws/devel/.catkin"),
        *(Path(path) for path in EXPECTED_HOOK_PATHS),
        Path("/opt/ros/noetic/share/rosbash/rosbash"),
    ]
    BASE.require(len(paths) == 23, "EXACT_SOURCE_CLOSURE_COUNT")
    return {
        str(path): BASE.identity(path.resolve()) for path in paths
    }


def generated_setup_snapshots() -> dict[str, Any]:
    environment = environment_updates()
    opt_environment = dict(environment)
    opt_environment["CATKIN_SHELL"] = "bash"
    commands = {
        "ros_noetic": ["/opt/ros/noetic/_setup_util.py"],
        "vins_devel_after_ros": [
            "/usr/bin/bash",
            "-c",
            "set -euo pipefail; source /opt/ros/noetic/setup.bash; "
            'CATKIN_SHELL=bash "$VINS_WS/devel/_setup_util.py"',
        ],
    }
    result: dict[str, Any] = {}
    for name, command in commands.items():
        process = subprocess.run(
            command,
            cwd=str(BASE.OVERLAY),
            env=opt_environment if name == "ros_noetic" else environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        BASE.require(
            process.returncode == 0,
            f"SETUP_SNAPSHOT_RC:{name}:{process.returncode}:{process.stderr[-400:]}",
        )
        lines = process.stdout.decode("utf-8").splitlines()
        hook_paths = []
        for line in lines:
            if not line.startswith("export _CATKIN_ENVIRONMENT_HOOKS_"):
                continue
            if "_WORKSPACE=" in line or "_COUNT=" in line:
                continue
            hook_paths.append(line.split("=", 1)[1].strip().strip('"'))
        BASE.require(hook_paths == EXPECTED_HOOK_PATHS, f"SETUP_HOOK_ORDER:{name}")
        result[name] = {
            "size_bytes": len(process.stdout),
            "sha256": hashlib.sha256(process.stdout).hexdigest(),
            "hook_paths_in_order": hook_paths,
        }
    BASE.require(
        result["ros_noetic"]["sha256"]
        == "861f0104be125514b7a8ff0040344d274b2d12ce8d4c7c4984b91c87617c5398",
        "ROS_SETUP_SNAPSHOT_IDENTITY",
    )
    BASE.require(
        result["vins_devel_after_ros"]["sha256"]
        == "73fa888d619fdeded6db203cdf5cc50df64a49ab726c64b4a5b78790f9723c7a",
        "VINS_SETUP_SNAPSHOT_IDENTITY",
    )
    return result


def post_source_environment_equivalence() -> dict[str, Any]:
    command_body = (
        'source "$ROOT/scripts/learned_seedchain_env.sh"; '
        "source /opt/ros/noetic/setup.bash; "
        'source "$VINS_WS/devel/setup.bash"; env -0'
    )
    environments = {
        "reference_without_nounset": ORIGINAL_ENVIRONMENT_UPDATES(),
        "attempt002_with_nounset": environment_updates(),
    }
    observed: dict[str, dict[str, str]] = {}
    for name, environment in environments.items():
        flags = "set -eo pipefail; " if name == "reference_without_nounset" else "set -euo pipefail; "
        process = subprocess.run(
            ["/usr/bin/bash", "-c", flags + command_body],
            cwd=str(BASE.OVERLAY),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        BASE.require(
            process.returncode == 0,
            f"POST_SOURCE_ENV_RC:{name}:{process.returncode}:{process.stderr[-400:]}",
        )
        entries: dict[str, str] = {}
        for item in process.stdout.split(b"\0"):
            if not item or b"=" not in item:
                continue
            key, raw_value = item.split(b"=", 1)
            decoded_key = key.decode("utf-8")
            if decoded_key in {"_", "SHLVL"}:
                continue
            entries[decoded_key] = raw_value.decode("utf-8")
        observed[name] = dict(sorted(entries.items()))
    BASE.require(
        observed["reference_without_nounset"] == observed["attempt002_with_nounset"],
        "POST_SOURCE_ENVIRONMENT_NOT_EQUIVALENT",
    )
    canonical = BASE.canonical_json(observed["attempt002_with_nounset"])
    return {
        "equivalent_after_source": True,
        "excluded_shell_bookkeeping_keys": ["SHLVL", "_"],
        "environment_key_count": len(observed["attempt002_with_nounset"]),
        "canonical_environment_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def strict_source_chain_fingerprint() -> dict[str, Any]:
    code = r'''
import json, os, pathlib, sys
import torch
import uw_frontend.ros.export_vins_features as exporter
value = {
    "sys_executable": sys.executable,
    "exporter_file": str(pathlib.Path(exporter.__file__).resolve()),
    "torch_cuda_available": torch.cuda.is_available(),
    "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "ROS_DISTRO": os.environ.get("ROS_DISTRO"),
    "ROS_MASTER_URI": os.environ.get("ROS_MASTER_URI"),
    "ROS_VERSION": os.environ.get("ROS_VERSION"),
    "ROS_PYTHON_VERSION": os.environ.get("ROS_PYTHON_VERSION"),
    "ROS_ROOT": os.environ.get("ROS_ROOT"),
    "ROS_ETC_DIR": os.environ.get("ROS_ETC_DIR"),
    "ROS_PACKAGE_PATH": os.environ.get("ROS_PACKAGE_PATH"),
    "CMAKE_PREFIX_PATH": os.environ.get("CMAKE_PREFIX_PATH"),
    "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH"),
    "PATH": os.environ.get("PATH"),
    "PYTHONPATH": os.environ.get("PYTHONPATH"),
}
print(json.dumps(value, sort_keys=True))
'''
    environment = environment_updates()
    environment["AQUAFE_ATTEMPT2_STRICT_CODE"] = code
    process = subprocess.run(
        [
            "/usr/bin/bash",
            "-c",
            "set -euo pipefail; "
            'source "$ROOT/scripts/learned_seedchain_env.sh"; '
            "source /opt/ros/noetic/setup.bash; "
            'source "$VINS_WS/devel/setup.bash"; '
            'python3 -c "$AQUAFE_ATTEMPT2_STRICT_CODE"',
        ],
        cwd=str(BASE.OVERLAY),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    BASE.require(
        process.returncode == 0,
        f"STRICT_SOURCE_CHAIN_RC:{process.returncode}:{process.stderr[-400:]}",
    )
    try:
        value = json.loads(process.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise BASE.FrontendError("STRICT_SOURCE_CHAIN_JSON") from error
    BASE.require(
        Path(str(value.get("sys_executable", ""))).resolve() == BASE.CUDA_PYTHON.resolve(),
        "STRICT_SOURCE_CHAIN_PYTHON",
    )
    BASE.require(
        value.get("exporter_file")
        == str((BASE.OVERLAY / "uw_frontend/ros/export_vins_features.py").resolve()),
        "STRICT_SOURCE_CHAIN_EXPORTER",
    )
    BASE.require(value.get("torch_cuda_available") is True, "STRICT_SOURCE_CHAIN_CUDA")
    expected_ros = {
        "ROS_DISTRO": "noetic",
        "ROS_MASTER_URI": "http://localhost:11311",
        "ROS_VERSION": "1",
        "ROS_PYTHON_VERSION": "3",
        "ROS_ROOT": "/opt/ros/noetic/share/ros",
        "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
    }
    for key, expected in expected_ros.items():
        BASE.require(value.get(key) == expected, f"STRICT_SOURCE_CHAIN_{key}")
    prefixes = str(value.get("CMAKE_PREFIX_PATH") or "").split(os.pathsep)
    expected_prefixes = [
        "/home/ma/SLAM/VINS-Fusion-origin/devel",
        "/home/ma/dave_ws/devel",
        "/home/ma/uuv_ws/devel",
        "/opt/ros/noetic",
    ]
    BASE.require(prefixes == expected_prefixes, "STRICT_SOURCE_CHAIN_PREFIXES")
    value["pinned_setup_superset_files"] = source_chain_identity(prefixes)
    value["exact_sourced_closure_files"] = exact_sourced_closure()
    value["generated_setup_snapshots"] = generated_setup_snapshots()
    value["bootstrap_reference_equivalence"] = post_source_environment_equivalence()
    value["hook_source_rounds"] = 2
    value["set_euo_pipefail_verified"] = True
    return value


def environment_fingerprint() -> dict[str, Any]:
    value = ORIGINAL_ENVIRONMENT_FINGERPRINT()
    previous_sha = value.pop("runtime_environment_manifest_sha256")
    value["attempt001_base_runtime_manifest_sha256"] = previous_sha
    value["attempt002_strict_source_chain"] = strict_source_chain_fingerprint()
    value["attempt002_amendment"] = BASE.require_identity(
        AMENDMENT, ATTEMPT1_IDENTITIES[AMENDMENT]
    )
    value["runtime_environment_manifest_sha256"] = hashlib.sha256(
        BASE.canonical_json(value)
    ).hexdigest()
    return value


def fixed_inputs() -> dict[str, Any]:
    value = ORIGINAL_FIXED_INPUTS()
    for path, expected in ATTEMPT1_IDENTITIES.items():
        value[str(path)] = BASE.require_identity(path, expected)
    wrapper = Path(__file__).resolve()
    value[str(wrapper)] = BASE.identity(wrapper)
    BASE.require(
        ATTEMPT1_RUN.is_dir() and not ATTEMPT1_RUN.is_symlink(),
        "ATTEMPT001_RUN_DIRECTORY",
    )
    BASE.require(not any(ATTEMPT1_RUN.iterdir()), "ATTEMPT001_RUN_NOT_EMPTY")
    return value


def infrastructure_context(stage: str, environment: Any = None) -> dict[str, Any]:
    common = {
        "manual_additive_infrastructure_correction": stage == "klt",
        "automatic_retry_count": 0,
        "attempt001_data_processing_exporter_invocation_count": 0,
        "attempt001_method_output_count": 0,
        "attempt001_preflight_read_raw_contract": True,
        "attempt001_preflight_imported_modules": True,
        "attempt001_runner": BASE.require_identity(
            BASE_RUNNER, ATTEMPT1_IDENTITIES[BASE_RUNNER]
        ),
        "attempt002_runner": BASE.identity(Path(__file__).resolve()),
        "complete_july_environment_reproduction": False,
        "method_label": "recovered seven-file July core plus newly frozen transitive closure",
        "attempt002_amendment": BASE.identity(AMENDMENT),
        "attempt001_terminal_evidence": {
            str(path): BASE.require_identity(path, expected)
            for path, expected in ATTEMPT1_IDENTITIES.items()
            if path not in (BASE_RUNNER, AMENDMENT)
        },
        "attempt001_run_directory": {
            "path": str(ATTEMPT1_RUN),
            "entry_count": 0,
            "features_bag_present": False,
            "frontend_metrics_present": False,
            "camera_config_present": False,
            "vins_or_accuracy_present": False,
        },
    }
    if stage == "klt":
        previous_claim_path = BASE.FRONTEND_ROOT / "klt_process_start_claim_v1.json"
        previous_claim = json.loads(previous_claim_path.read_text(encoding="utf-8"))
        common.update(
            {
                "classification": "INVALID_PRE_EXPORT_INFRASTRUCTURE_BOOTSTRAP_FAILURE_RECOVERY",
                "campaign_supervisor_launch_count_including_attempt002": 2,
                "algorithmic_export_attempt_index": 1,
                "attempt002_no_further_attempt_if_exporter_or_audit_fails": True,
                "outcome_information_used_to_change_method": [],
                "permitted_environment_delta": {
                    "added": {
                        "ROS_DISTRO": "noetic",
                        "ROS_MASTER_URI": "http://localhost:11311",
                    },
                    "changed": {
                        "TAG": {
                            "before": previous_claim["environment"]["TAG"],
                            "after": BASE.KLT_TAG,
                            "reason": "additive output namespace",
                        }
                    },
                },
            }
        )
        if isinstance(environment, dict):
            previous_environment = previous_claim["environment"]
            keys = sorted(set(previous_environment) | set(environment))
            observed = {
                key: {
                    "before": previous_environment.get(key),
                    "after": environment.get(key),
                }
                for key in keys
                if previous_environment.get(key) != environment.get(key)
            }
            BASE.require(
                set(observed) == {"ROS_DISTRO", "ROS_MASTER_URI", "TAG"},
                f"ATTEMPT002_ENVIRONMENT_DELTA:{sorted(observed)}",
            )
            BASE.require(
                previous_claim.get("command")
                == [
                    "/usr/bin/bash",
                    str(BASE.OVERLAY / "scripts/run_learned_seedchain_eval.sh"),
                    "aqualoc_archaeo",
                    "8",
                    "0",
                    "4660",
                    "klt",
                    "2",
                ],
                "ATTEMPT001_COMMAND_IDENTITY",
            )
            common["observed_environment_delta"] = observed
            common["algorithm_command_unchanged"] = True
    else:
        common.update(
            {
                "classification": "FIRST_XFEAT_SUPERVISOR_USING_VALIDATED_ROS_BOOTSTRAP",
                "method_supervisor_attempt_index": 1,
                "automatic_method_retry": False,
            }
        )
    common["campaign_single_popen_claim_permitted"] = False
    common["single_supervisor_popen_claim_scope"] = "this_attempt_only"
    return common


def write_exclusive(path: Path, value: Any) -> None:
    payload = value
    attempt_paths = {
        BASE.KLT_CLAIM,
        BASE.KLT_RECEIPT,
        BASE.KLT_FAILURE,
        BASE.XFEAT_CLAIM,
        BASE.XFEAT_RECEIPT,
        BASE.XFEAT_FAILURE,
    }
    if path in attempt_paths and isinstance(value, dict):
        payload = dict(value)
        stage = str(value.get("stage", ""))
        payload["infrastructure_correction_context"] = infrastructure_context(
            stage, value.get("environment")
        )
        if path in (BASE.KLT_RECEIPT, BASE.XFEAT_RECEIPT):
            payload["qualified_status"] = (
                "PASS_FRONTEND_EXPORT_ACCEPTED_AFTER_PRE_EXPORT_INFRASTRUCTURE_CORRECTION"
                if stage == "klt"
                else "PASS_FIRST_XFEAT_FRONTEND_EXPORT_ACCEPTED_WITH_CORRECTED_BOOTSTRAP"
            )
        if path in (BASE.KLT_FAILURE, BASE.XFEAT_FAILURE):
            payload["qualified_status"] = "FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT"
    ORIGINAL_WRITE_EXCLUSIVE(path, payload)


# Patch only the environment/input evidence functions and additive output names.
BASE.environment_updates = environment_updates
BASE.environment_fingerprint = environment_fingerprint
BASE.fixed_inputs = fixed_inputs
BASE.write_exclusive = write_exclusive

BASE.KLT_TAG = "a08_recoveredjuly_hist0000_4660_klt_export_attempt002_rosseed_v1"
BASE.KLT_RUN = BASE.RUN_ROOT / f"external_klt_every2_{BASE.KLT_TAG}"
BASE.XFEAT_TAG_BASE = (
    "a08_recoveredjuly_hist0000_4660_oldarb_attempt002_rosseed_v1"
)

BASE.KLT_CLAIM = BASE.FRONTEND_ROOT / "klt_attempt002_process_start_claim_v1.json"
BASE.KLT_RECEIPT = BASE.FRONTEND_ROOT / "klt_attempt002_export_receipt_v1.json"
BASE.KLT_FAILURE = BASE.FRONTEND_ROOT / "klt_attempt002_export_failure_v1.json"
BASE.KLT_LOG = BASE.FRONTEND_ROOT / "klt_attempt002_supervisor_process.log"
BASE.XFEAT_CLAIM = BASE.FRONTEND_ROOT / "xfeat_attempt002_process_start_claim_v1.json"
BASE.XFEAT_RECEIPT = BASE.FRONTEND_ROOT / "xfeat_attempt002_export_receipt_v1.json"
BASE.XFEAT_FAILURE = BASE.FRONTEND_ROOT / "xfeat_attempt002_export_failure_v1.json"
BASE.XFEAT_LOG = BASE.FRONTEND_ROOT / "xfeat_attempt002_supervisor_process.log"


def main() -> int:
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "audit-all":
            expected_klt = fixed_inputs()
            expected_xfeat = dict(expected_klt)
            expected_xfeat[str(BASE.KLT_RECEIPT)] = BASE.identity(BASE.KLT_RECEIPT)
            for receipt_path, expected in (
                (BASE.KLT_RECEIPT, expected_klt),
                (BASE.XFEAT_RECEIPT, expected_xfeat),
            ):
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                BASE.require(receipt.get("inputs_before") == expected, "ATTEMPT002_INPUTS_BEFORE_DRIFT")
                BASE.require(receipt.get("inputs_after") == expected, "ATTEMPT002_INPUTS_AFTER_DRIFT")
        return int(BASE.main())
    except (BASE.FrontendError, OSError, ValueError) as error:
        print(f"FRONTEND_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
