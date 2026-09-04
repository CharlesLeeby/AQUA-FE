#!/usr/bin/env python3
"""Internal backend-only adapter for one locked P07 replay.

The formal entrypoint is ``run_p07_backend_replay_job_v1.py``.  This module is
imported by that governed job; direct CLI execution is intentionally rejected.
Feature arms receive a read-only ``/proc/self/fd/N`` lease, never the frozen
bag pathname, and all exporter controls are forced off.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import signal
import socket
import subprocess
import time
from datetime import datetime
from contextlib import ExitStack
from pathlib import Path
from typing import Any, BinaryIO, Mapping

try:
    from scripts import check_p07_backend_replay_input_v1 as input_checker
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import prepare_p07_backend_replay_config_v1 as config_helper
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import check_p07_backend_replay_input_v1 as input_checker  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import prepare_p07_backend_replay_config_v1 as config_helper  # type: ignore


SCHEMA_VERSION = "isj-p07-backend-replay-adapter-result-v1"
COMMAND_SCHEMA_VERSION = "isj-p07-backend-replay-adapter-command-v1"
JOB_AUTHORITY_SCHEMA_VERSION = "isj-p07-backend-job-authority-v1"

RUNNERS = {
    "ntnu": "scripts/run_ntnu_vins_eval.sh",
    "aqualoc_archaeology": "scripts/run_aqualoc_archaeo_vins_eval.sh",
    "aqualoc_harbor": "scripts/run_aqualoc_real_vins_eval.sh",
    "afrl": "scripts/run_afrl_cave_vins_eval.sh",
}
RUN_ROOTS = {
    "ntnu": "logs/ntnu_vins",
    "aqualoc_archaeology": "logs/aqualoc_archaeo_vins",
    "aqualoc_harbor": "logs/aqualoc_real_vins",
    "afrl": "logs/afrl_cave_v31",
}
REPLAY_ONLY_RUNNER = "scripts/run_p07_backend_replay_only_v1.sh"
CONFIG_HELPER = "scripts/prepare_p07_backend_replay_config_v1.py"

_FIXED_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class AdapterViolation(common.BackendReplayViolation):
    """The backend-only adapter could not preserve its execution envelope."""


def _row_sha256(row: Mapping[str, str]) -> str:
    return common.sha256_bytes(
        json.dumps(
            dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    )


def validate_job_authority(
    row: Mapping[str, str],
    *,
    root: Path,
    attempt_dir: Path,
    lock_fd: int,
    run_dir_lease: common.DirectoryLease,
    authority: Mapping[str, str],
) -> dict[str, Any]:
    expected_path = attempt_dir / "job_authority_v1.json"
    raw_path = authority.get("path", "")
    path = common.output_path(root, raw_path, label="job authority")
    if common.lexical_absolute(path) != common.lexical_absolute(expected_path):
        raise AdapterViolation("job authority is outside the frozen attempt")
    if common.sha256(path) != authority.get("sha256"):
        raise AdapterViolation("job authority SHA-256 mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterViolation("invalid job authority JSON") from error
    if not isinstance(payload, dict):
        raise AdapterViolation("job authority is not an object")
    lock_info = os.fstat(lock_fd)
    expected = {
        "schema_version": JOB_AUTHORITY_SCHEMA_VERSION,
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "row_sha256": _row_sha256(row),
        "attempt_dir": common.display_path(root, attempt_dir),
        "run_dir": common.display_path(root, Path(run_dir_lease.path)),
        "run_dir_device": run_dir_lease.device,
        "run_dir_inode": run_dir_lease.inode,
        "global_lock_device": lock_info.st_dev,
        "global_lock_inode": lock_info.st_ino,
    }
    differences = {
        key: {"expected": value, "observed": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if differences:
        raise AdapterViolation(f"job authority identity mismatch: {differences}")
    token = authority.get("token")
    if not isinstance(token, str) or len(token) != 64 or payload.get("token") != token:
        raise AdapterViolation("job authority capability token mismatch")
    execution_lock = common.workspace_path(
        root, str(payload.get("execution_lock_path", "")), label="authority execution lock"
    )
    if common.sha256(execution_lock) != payload.get("execution_lock_sha256"):
        raise AdapterViolation("job authority execution-lock hash mismatch")
    intent = common.workspace_path(
        root, str(payload.get("attempt_intent_path", "")), label="attempt intent"
    )
    if (
        common.sha256(intent) != payload.get("attempt_intent_sha256")
        or not isinstance(payload.get("attempt_intent_hash"), str)
    ):
        raise AdapterViolation("job authority attempt-intent binding mismatch")
    try:
        intent_payload = json.loads(intent.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterViolation("invalid attempt-intent JSON") from error
    if (
        not isinstance(intent_payload, dict)
        or intent_payload.get("attempt_intent_hash")
        != payload.get("attempt_intent_hash")
        or common.canonical_json_hash(intent_payload, "attempt_intent_hash")
        != payload.get("attempt_intent_hash")
        or intent_payload.get("run_id") != row["run_id"]
        or intent_payload.get("queue_index") != int(row["queue_index"])
        or intent_payload.get("g0_execution_authority_hash")
        != payload.get("g0_execution_authority_hash")
        or intent_payload.get("g0_evaluation_lock_hash")
        != payload.get("g0_evaluation_lock_hash")
    ):
        raise AdapterViolation("attempt-intent identity/self-hash drift")
    preflight_identity = attempt_dir / "data_identity_preflight.json"
    if common.sha256(preflight_identity) != payload.get(
        "data_identity_preflight_sha256"
    ):
        raise AdapterViolation("job authority data-identity preflight drift")
    journal_raw = payload.get("attempt_state_journal")
    if common.output_path(root, str(journal_raw), label="attempt state journal") != (
        attempt_dir / "attempt_state_v1.jsonl"
    ):
        raise AdapterViolation("job authority state-journal path drift")
    registry = common.workspace_path(
        root, str(payload.get("registry_path", "")), label="authority registry"
    )
    fields, rows = common.read_csv(registry)
    if not {"run_id", "registry_event_id", "status"}.issubset(fields):
        raise AdapterViolation("job authority registry header is incomplete")
    chain = [item for item in rows if item.get("run_id") == row["run_id"]]
    if (
        not chain
        or chain[-1].get("status") != "RUNNING"
        or chain[-1].get("registry_event_id") != payload.get("registry_event_id")
    ):
        raise AdapterViolation("job authority is not bound to the latest RUNNING event")
    common.verify_directory_lease(run_dir_lease, require_empty=True)
    return payload


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def assert_ros_port_available(port: int) -> None:
    if port < 1024 or port > 65535:
        raise AdapterViolation(f"invalid frozen ROS port: {port}")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as error:
        raise AdapterViolation(f"frozen ROS port is unavailable: {port}") from error
    finally:
        probe.close()


def _manifest_row(root: Path, family: str, sequence: str) -> dict[str, str]:
    path = root / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("dataset_family") == family and row.get("sequence") == sequence
        ]
    if len(rows) != 1:
        raise AdapterViolation(f"missing unique data eligibility row for {family}/{sequence}")
    return rows[0]


def _manifest_input(root: Path, row: Mapping[str, str], field: str) -> str:
    raw = row.get(field, "")
    if not raw:
        raise AdapterViolation(f"data eligibility row lacks {field}")
    path = common.workspace_path(root, raw, label=f"data manifest {field}")
    return os.fspath(path)


def _afrl_camera_topic(path: Path) -> str:
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        topic = payload["cam0"]["rostopic"]
    except Exception as error:
        raise AdapterViolation(f"cannot resolve AFRL cam0 topic from {path}") from error
    if not isinstance(topic, str) or not topic.startswith("/"):
        raise AdapterViolation("invalid AFRL cam0 ROS topic")
    return topic


def predicted_run_dir(row: Mapping[str, str], *, root: Path) -> Path:
    family = row["dataset_family"]
    if family not in RUN_ROOTS:
        raise AdapterViolation(f"unsupported backend dataset family: {family}")
    predicted = root / RUN_ROOTS[family] / (
        f"{row['runner_mode']}_{row['runner_method']}_every{row['runner_every_n']}_"
        f"{row['runner_tag']}"
    )
    expected = common.output_path(root, row["expected_run_dir"], label="expected run dir")
    if common.lexical_absolute(predicted) != expected:
        raise AdapterViolation(
            f"direct runner output differs from queue: predicted={predicted} expected={expected}"
        )
    return expected


def _sequence_number(value: str, prefix: str) -> str:
    if not value.startswith(prefix) or not value[len(prefix) :].isdigit():
        raise AdapterViolation(f"invalid {prefix} sequence: {value}")
    return str(int(value[len(prefix) :]))


def build_prepare_argv(
    row: Mapping[str, str],
    *,
    root: Path,
    runtime_context: common.RuntimeConsumptionContext | None = None,
) -> list[str]:
    """Build the dataset preparation command.

    The governed environment always forces this legacy runner to
    ``RUN_VINS=0``.  It may prepare raw/cache/config inputs, but it is never the
    replay entrypoint and therefore cannot reach its embedded evaluator.
    """
    common.validate_queue_row(row)
    family = row["dataset_family"]
    if family not in RUNNERS:
        raise AdapterViolation(f"unsupported backend dataset family: {family}")
    start = row["runner_start"]
    end_or_duration = row["runner_end_or_duration"]
    every_n = row["runner_every_n"]
    sequence = row["sequence"]

    if family in {"aqualoc_archaeology", "aqualoc_harbor"}:
        if row["runner_unit"] != "frame":
            raise AdapterViolation("AQUALOC direct runner requires frame bounds")
    elif row["runner_unit"] != "second":
        raise AdapterViolation("NTNU/AFRL direct runner requires second bounds")

    if row["arm"] == common.B0_ARM:
        arguments = [family, sequence, start, end_or_duration, every_n]
        if runtime_context is not None:
            return runtime_context.shell_argv("b0_guard_wrapper", arguments)
        return [
            "bash",
            os.fspath(root / "scripts/run_isj_b0_native_vins_guarded_v1.sh"),
            *arguments,
        ]

    runner = os.fspath(root / RUNNERS[family])
    method = row["runner_method"]
    if family == "ntnu":
        args = ["external", sequence, start, end_or_duration, method, every_n]
    elif family == "aqualoc_archaeology":
        args = [
            "external",
            _sequence_number(sequence, "A"),
            start,
            end_or_duration,
            method,
            every_n,
        ]
    elif family == "aqualoc_harbor":
        _sequence_number(sequence, "H")
        args = ["external", start, end_or_duration, method, every_n]
    else:
        args = ["external", method, start, end_or_duration, every_n]
    if runtime_context is not None:
        role = {
            "ntnu": "direct_runner_ntnu",
            "aqualoc_archaeology": "direct_runner_aqualoc_archaeology",
            "aqualoc_harbor": "direct_runner_aqualoc_harbor",
            "afrl": "direct_runner_afrl",
        }[family]
        return runtime_context.shell_argv(role, args)
    return ["bash", runner, *args]


def _mode(row: Mapping[str, str]) -> str:
    mode = row["runner_mode"]
    expected = "origin" if row["arm"] == common.B0_ARM else "external"
    if mode != expected:
        raise AdapterViolation(
            f"backend runner mode differs from arm contract: {mode} != {expected}"
        )
    return mode


def vins_config_path(row: Mapping[str, str], *, root: Path) -> Path:
    run_dir = predicted_run_dir(row, root=root)
    mode = _mode(row)
    names = {
        "ntnu": f"vins_ntnu_{mode}.yaml",
        "aqualoc_archaeology": f"vins_aqualoc_archaeo_{mode}.yaml",
        "aqualoc_harbor": f"vins_aqualoc_{mode}.yaml",
        "afrl": f"vins_afrl_cave_{mode}.yaml",
    }
    return run_dir / names[row["dataset_family"]]


def camera_config_path(row: Mapping[str, str], *, root: Path) -> Path:
    run_dir = predicted_run_dir(row, root=root)
    family = row["dataset_family"]
    if family == "aqualoc_archaeology":
        matches = sorted(run_dir.glob("aqualoc_archaeo*_pinhole.yaml"))
        if len(matches) != 1:
            raise AdapterViolation(
                "AQUALOC archaeology prep lacks one camera configuration"
            )
        return matches[0]
    names = {
        "ntnu": "ntnu_cam0_kannala_brandt.yaml",
        "aqualoc_harbor": "aqualoc_harbor07_kannala.yaml",
        "afrl": "afrl_cave_cam0_pinhole.yaml",
    }
    try:
        return run_dir / names[family]
    except KeyError as error:
        raise AdapterViolation(f"unsupported camera-config family: {family}") from error


def _derived_replay_config_bytes(
    row: Mapping[str, str],
    *,
    original: bytes,
    camera_name: str,
    camera_proc_path: str,
    root: Path,
) -> bytes:
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AdapterViolation("prepared VINS config is not UTF-8") from error
    try:
        config_helper.validate_config_text(
            row["dataset_family"],
            _mode(row),
            text,
            camera_config_name=camera_name,
            vins_output=predicted_run_dir(row, root=root) / "vins_output",
        )
    except config_helper.ConfigError as error:
        raise AdapterViolation(f"prepared VINS config is invalid: {error}") from error
    pattern = re.compile(
        rf'^cam0_calib: "{re.escape(camera_name)}"$', re.MULTILINE
    )
    if len(pattern.findall(text)) != 1:
        raise AdapterViolation("prepared VINS config camera binding is not exact")
    derived = pattern.sub(f'cam0_calib: "{camera_proc_path}"', text)
    if camera_proc_path not in derived or derived.count("cam0_calib:") != 1:
        raise AdapterViolation("cannot derive sealed camera-config binding")
    return derived.encode("utf-8")


def origin_play_bag(row: Mapping[str, str], *, root: Path) -> Path:
    """Resolve the preparation output consumed by an origin-only B0 replay."""
    if row["arm"] != common.B0_ARM:
        raise AdapterViolation("only B0 may resolve an origin play bag")
    family = row["dataset_family"]
    if family == "ntnu":
        manifest = _manifest_row(root, family, row["sequence"])
        return common.workspace_path(
            root, manifest["raw_input_path"], label="NTNU origin raw bag"
        )
    if family == "aqualoc_archaeology":
        seq = int(_sequence_number(row["sequence"], "A"))
        return root / (
            "datasets/aqualoc/rosbags/"
            f"archaeo{seq:02d}_{row['runner_start']}_{row['runner_end_or_duration']}.bag"
        )
    if family == "aqualoc_harbor":
        seq = int(_sequence_number(row["sequence"], "H"))
        return root / (
            "datasets/aqualoc/rosbags/"
            f"harbor{seq:02d}_{row['runner_start']}_{row['runner_end_or_duration']}.bag"
        )
    if family == "afrl":
        return predicted_run_dir(row, root=root) / "cave_gennie_short.bag"
    raise AdapterViolation(f"unsupported origin family: {family}")


def prematerialized_preparation_bag(
    row: Mapping[str, str], *, root: Path
) -> Path:
    """Return the cache that must exist before a governed backend attempt.

    Formal backend replay never authorizes an AQUALOC/AFRL converter.  The
    exact cache is prepared before the execution lock and a missing cache is a
    pre-launch infrastructure failure, not permission to derive new bytes.
    """

    path = origin_play_bag(
        {**dict(row), "arm": common.B0_ARM},  # path resolution is arm-agnostic
        root=root,
    )
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise AdapterViolation(
            f"pre-materialized backend preparation bag is missing: {path}"
        ) from error
    import stat

    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AdapterViolation(
            f"pre-materialized backend preparation bag is not plain: {path}"
        )
    return path


def build_config_argv(
    row: Mapping[str, str],
    *,
    root: Path,
    runtime_context: common.RuntimeConsumptionContext | None = None,
) -> list[str]:
    arguments = [
        "--family",
        row["dataset_family"],
        "--mode",
        _mode(row),
        "--run-dir",
        os.fspath(predicted_run_dir(row, root=root)),
    ]
    if runtime_context is not None:
        return runtime_context.python_argv("config_helper", arguments)
    return ["python3", os.fspath(root / CONFIG_HELPER), *arguments]


def build_backend_argv(
    row: Mapping[str, str],
    *,
    root: Path,
    play_bag: str | None = None,
    frozen_b0_play_bag: Path | None = None,
    vins_config: str | None = None,
    runtime_context: common.RuntimeConsumptionContext | None = None,
) -> list[str]:
    """Build the evaluator-free ROS replay command.

    Feature arms must supply the sealed memfd pathname.  B0 resolves the raw
    prepared bag from its immutable queue row.
    """
    common.validate_queue_row(row)
    mode = _mode(row)
    if mode == "external":
        if play_bag is None or not play_bag.startswith("/proc/self/fd/"):
            raise AdapterViolation("external replay requires a sealed memfd path")
    else:
        if frozen_b0_play_bag is None:
            # Non-formal helper compatibility.  Formal execute_replay always
            # supplies the exact execution-lock-bound play input.
            frozen_b0_play_bag = origin_play_bag(row, root=root)
        expected = common.lexical_absolute(frozen_b0_play_bag)
        if play_bag is None:
            raise AdapterViolation("B0 replay requires a sealed play-input fd")
        elif not play_bag.startswith("/proc/self/fd/"):
            raise AdapterViolation("B0 replay bag differs from frozen play input")
    config_argument = vins_config or os.fspath(vins_config_path(row, root=root))
    arguments = [
        row["dataset_family"],
        mode,
        play_bag,
        os.fspath(predicted_run_dir(row, root=root)),
        config_argument,
        str(13000 + int(row["queue_index"])),
    ]
    if runtime_context is not None:
        return runtime_context.shell_argv("replay_only_runner", arguments)
    return ["bash", os.fspath(root / REPLAY_ONLY_RUNNER), *arguments]


def safe_environment(
    row: Mapping[str, str],
    *,
    root: Path,
    attempt_dir: Path,
    feature_bag_fd_path: str | None,
    b0_play_input_path: str | Path | None = None,
    preparation_bag_fd_path: str | None = None,
    runtime_context: common.RuntimeConsumptionContext | None = None,
) -> dict[str, str]:
    # Do not inherit arbitrary runner knobs, ROS state, loader injection, or
    # frontend/export controls from the operator shell.  The hashed runners
    # source their own ROS/VINS setup; only inert account metadata is retained.
    environment = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": _FIXED_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "MPLBACKEND": "Agg",
    }
    if runtime_context is not None:
        common.validate_frozen_ros_platform()
        environment = common.sealed_runtime_environment(
            runtime_context,
            extra={"MPLBACKEND": "Agg"},
        )
        # Fixed root-owned ROS1 runtime inputs replace both catkin setup.bash
        # sources.  Sealed Python targets use -I and therefore ignore this
        # PYTHONPATH; shell preparation helpers need it for root-owned rosbag.
        environment.update(common.FROZEN_ROS_ENVIRONMENT)
        environment["AQUAFE_P07_FROZEN_ROS_ENV"] = "1"
    environment.update(
        {
            "ROOT": os.fspath(root),
            "VINS_WS": os.fspath(common.VINS_ORIGIN),
            # The legacy family runners are preparation-only.  The separate,
            # hash-bound replay-only launcher starts ROS/VINS after preparation.
            "RUN_VINS": "0",
            "BACKEND_REPLAY_ONLY": "1",
            "RUN_EVALUATION": "0",
            "FORCE_EXPORT": "0",
            "FORCE_RAW": "0",
            "EXPORT_FEATURES": "0",
            "VINS_MULTIPLE_THREAD": "0",
            "TAG": row["runner_tag"],
            "RUN_DIR": os.fspath(predicted_run_dir(row, root=root)),
            "PORT": str(13000 + int(row["queue_index"])),
            "BACKEND_QUALITY_MODE": "vins_safe",
            "BACKEND_QUALITY_FLOOR": "0.80",
            "BACKEND_QUALITY_ALPHA": "0.65",
            "RAW_QUALITY_TO_BACKEND": "0",
            "CONSTANT_QUALITY_TO_BACKEND": "0",
            "BACKEND_LEARNED_QUALITY_SCALE": "1.0",
            "BACKEND_SP_LG_QUALITY_SCALE": "1.0",
            "BACKEND_XFEAT_QUALITY_SCALE": "1.0",
            "BACKEND_LOFTR_QUALITY_SCALE": "1.0",
            "BACKEND_LEARNED_QUALITY_CONST": "",
            "BACKEND_SP_LG_QUALITY_CONST": "",
            "BACKEND_XFEAT_QUALITY_CONST": "",
            "BACKEND_LOFTR_QUALITY_CONST": "",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    if runtime_context is not None:
        environment.update(
            {
                "AQUAFE_P07_SEALED_BOOTSTRAP": runtime_context.proc_path(
                    "sealed_runtime_bootstrap"
                ),
                "AQUAFE_P07_PYTHON_INTERPRETER": runtime_context.proc_path(
                    "python_interpreter"
                ),
                "AQUAFE_P07_B0_CHECKER_MODULE": (
                    "scripts.check_b0_vins_origin_identity_v1"
                ),
                "AQUAFE_P07_NATIVEQ_CONTRACT": runtime_context.proc_path(
                    "nativeq_contract_document"
                ),
                "AQUAFE_P07_RUNNER_NTNU": runtime_context.proc_path(
                    "direct_runner_ntnu"
                ),
                "AQUAFE_P07_RUNNER_AQUALOC_ARCHAEOLOGY": (
                    runtime_context.proc_path("direct_runner_aqualoc_archaeology")
                ),
                "AQUAFE_P07_RUNNER_AQUALOC_HARBOR": runtime_context.proc_path(
                    "direct_runner_aqualoc_harbor"
                ),
                "AQUAFE_P07_RUNNER_AFRL": runtime_context.proc_path(
                    "direct_runner_afrl"
                ),
                "AQUAFE_P07_VINS_BINARY": runtime_context.proc_path("vins_binary"),
                "AQUAFE_P07_VINS_LIB": runtime_context.proc_path(
                    "vins_shared_library"
                ),
                "AQUAFE_P07_CAMERA_MODELS_LIB": runtime_context.proc_path(
                    "camera_models_shared_library"
                ),
                "AQUAFE_P07_VINS_BINARY_SHA256": str(
                    runtime_context.entries["vins_binary"]["sha256"]
                ),
                "AQUAFE_P07_VINS_LIB_SHA256": str(
                    runtime_context.entries["vins_shared_library"]["sha256"]
                ),
                "AQUAFE_P07_CAMERA_MODELS_LIB_SHA256": str(
                    runtime_context.entries["camera_models_shared_library"]["sha256"]
                ),
                "AQUAFE_P07_ROSCORE": common.FROZEN_ROS_EXECUTABLES["roscore"],
                "AQUAFE_P07_ROSPARAM": common.FROZEN_ROS_EXECUTABLES["rosparam"],
                "AQUAFE_P07_ROSBAG": common.FROZEN_ROS_EXECUTABLES["rosbag"],
            }
        )
    if feature_bag_fd_path is not None:
        if not feature_bag_fd_path.startswith("/proc/self/fd/"):
            raise AdapterViolation("backend runner feature bag is not a read-only fd path")
        environment["FEATURE_BAG_OVERRIDE"] = feature_bag_fd_path
    else:
        environment.pop("FEATURE_BAG_OVERRIDE", None)
        environment["AQUAFE_B0_DECISION_DIR"] = os.fspath(
            attempt_dir / "b0_contract_decisions"
        )

    family = row["dataset_family"]
    manifest = _manifest_row(root, family, row["sequence"])
    if family == "ntnu":
        environment["NTNU_ROOT"] = os.fspath(
            root / "datasets/full_downloads/ntnu_hf"
        )
        environment["RAW_BAG"] = _manifest_input(root, manifest, "raw_input_path")
        environment["GT_TUM"] = _manifest_input(root, manifest, "reference_path")
    elif family == "aqualoc_archaeology":
        environment["RAW_TAR"] = _manifest_input(root, manifest, "raw_input_path")
        environment["GT_TXT"] = _manifest_input(root, manifest, "reference_path")
    elif family == "aqualoc_harbor":
        environment["HARBOR_SEQ"] = _sequence_number(row["sequence"], "H")
        environment["RAW_TAR"] = _manifest_input(root, manifest, "raw_input_path")
        environment["GT_TXT"] = _manifest_input(root, manifest, "reference_path")
    elif family == "afrl":
        base = root / "datasets/full_downloads/afrl_hf"
        camchain = base / f"camera_imu_parameters/camchain_{row['sequence']}.yaml"
        imu_yaml = base / "camera_imu_parameters/imu.yaml"
        if not camchain.is_file() or not imu_yaml.is_file():
            raise AdapterViolation("missing AFRL calibration inputs")
        environment.update(
            {
                "RAW_BAG": _manifest_input(root, manifest, "raw_input_path"),
                "GT_TXT": _manifest_input(root, manifest, "reference_path"),
                "CAMCHAIN": os.fspath(camchain),
                "IMU_YAML": os.fspath(imu_yaml),
                "CAMERA_KEY": "cam0",
                "SRC_IMAGE_TOPIC": _afrl_camera_topic(camchain),
                "IMAGE_SCALE": "0.5",
            }
        )
    if preparation_bag_fd_path is not None:
        if not preparation_bag_fd_path.startswith("/proc/self/fd/"):
            raise AdapterViolation("preparation bag is not a sealed fd")
        if family in {"ntnu", "aqualoc_archaeology", "aqualoc_harbor"}:
            environment["RAW_BAG"] = preparation_bag_fd_path
        elif family == "afrl":
            environment["SHORT_BAG"] = preparation_bag_fd_path
            environment["PREPARE_BAG"] = "0"
    if row["arm"] == common.B0_ARM and family == "ntnu":
        environment["PLAY_START"] = row["runner_start"]
        environment["PLAY_DURATION"] = row["runner_end_or_duration"]
    if row["arm"] == common.B0_ARM:
        if b0_play_input_path is None:
            raise AdapterViolation("B0 environment lacks frozen play input")
        frozen = os.fspath(b0_play_input_path)
        if not frozen.startswith("/proc/self/fd/"):
            raise AdapterViolation("B0 environment play input is not sealed")
        if family in {"ntnu", "aqualoc_archaeology"}:
            environment["RAW_BAG"] = frozen
        elif family == "aqualoc_harbor":
            # The harbor runner has a deterministic canonical cache pathname;
            # its existence is checked before launch.  Replay itself receives
            # only the sealed B0 input fd.
            pass
        elif family == "afrl":
            environment["SHORT_BAG"] = frozen
            environment["PREPARE_BAG"] = "0"
    if any(
        os.fspath(common.FORBIDDEN_VINS_WORKSPACE) in value
        for value in environment.values()
    ):
        raise AdapterViolation("sanitized environment still names forbidden VINS workspace")
    return environment


def _run_checked(
    argv: list[str],
    *,
    environment: Mapping[str, str],
    log: BinaryIO,
    pass_fds: tuple[int, ...] = (),
    timeout_s: int,
    state_journal: Path | None = None,
    state_context: Mapping[str, Any] | None = None,
    phase: str = "CONSUMER_GUARD",
) -> None:
    returncode, timed_out = _run_process(
        argv,
        environment=environment,
        log=log,
        timeout_s=timeout_s,
        pass_fds=pass_fds,
        state_journal=state_journal,
        state_context=state_context,
        phase=phase,
    )
    if timed_out:
        raise AdapterViolation("backend consumer contract guard timed out")
    if returncode != 0:
        raise AdapterViolation(f"backend consumer contract guard failed rc={returncode}")


def _run_required_phase(
    label: str,
    argv: list[str],
    *,
    environment: Mapping[str, str],
    log: BinaryIO,
    pass_fds: tuple[int, ...] = (),
    timeout_s: int,
    state_journal: Path | None = None,
    state_context: Mapping[str, Any] | None = None,
) -> None:
    returncode, timed_out = _run_process(
        argv,
        environment=environment,
        log=log,
        timeout_s=timeout_s,
        pass_fds=pass_fds,
        state_journal=state_journal,
        state_context=state_context,
        phase=label.upper().replace(" ", "_"),
    )
    if timed_out:
        raise AdapterViolation(f"backend {label} timed out")
    if returncode != 0:
        raise AdapterViolation(f"backend {label} failed rc={returncode}")


def _argv_sha256(argv: list[str]) -> str:
    return common.sha256_bytes(
        json.dumps(argv, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )


def _assert_pre_replay_boundary(run_dir: Path) -> None:
    forbidden = (
        run_dir / "vins_output/vio.csv",
        run_dir / "ape.txt",
        run_dir / "rpe.txt",
        run_dir / "ape_rpe.json",
    )
    collisions = [os.fspath(path) for path in forbidden if path.exists() or path.is_symlink()]
    if collisions:
        raise AdapterViolation(
            f"preparation crossed the replay/evaluation boundary: {collisions}"
        )


def _regular_file_identity(path: Path, *, label: str) -> dict[str, Any]:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise AdapterViolation(f"missing {label}: {path}") from error
    import stat

    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AdapterViolation(f"{label} is not a plain regular file: {path}")
    return {
        "path": os.fspath(common.lexical_absolute(path)),
        "size_bytes": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
    }


def run_consumer_guard(
    row: Mapping[str, str],
    *,
    root: Path,
    attempt_dir: Path,
    environment: Mapping[str, str],
    bag_proc_path: str,
    attestation_proc_path: str,
    bag_fd: int,
    attestation_fd: int,
    runtime_context: common.RuntimeConsumptionContext,
    log: BinaryIO,
    timeout_s: int,
    state_journal: Path | None = None,
    state_context: Mapping[str, Any] | None = None,
) -> Path:
    decision = attempt_dir / "backend_consumer_contract_decision.json"
    if row["arm"] in common.NATIVEQ_ARMS:
        arguments = [
            "--contract",
            runtime_context.proc_path("nativeq_contract_document"),
            "--feature-bag",
            bag_proc_path,
            "--bag-attestation",
            attestation_proc_path,
            "--decision-json",
            os.fspath(decision),
        ]
        argv = runtime_context.python_argv("nativeq_contract_checker", arguments)
    elif row["arm"] == common.M_ARM:
        frame_offset = "0" if row["dataset_family"] == "afrl" else "1"
        arguments = [
            "--contract",
            runtime_context.proc_path("xfeat_contract_document"),
            "--family",
            row["dataset_family"],
            "--every-n",
            row["runner_every_n"],
            "--frame-offset",
            frame_offset,
            "--run-vins",
            "1",
            "--method",
            "xfeat",
            "--preprocess",
            "adaptive_clahe",
            "--process-skipped-frames",
            "1",
            "--measurement-selection",
            "0",
            "--formal-three-layer-export",
            "0",
            "--vins-safe-source-selection",
            "0",
            "--export-max-features",
            "350",
            "--vins-max-cnt",
            "350",
            "--semidense-fallback-method",
            "none",
            "--vins-multiple-thread",
            "0",
            "--export-features",
            "1",
            "--force-export",
            "1",
            "--feature-bag",
            bag_proc_path,
            "--bag-attestation",
            attestation_proc_path,
            "--decision-json",
            os.fspath(decision),
        ]
        argv = runtime_context.python_argv("xfeat_contract_checker", arguments)
    else:
        raise AdapterViolation(f"no reused-bag consumer guard for {row['arm']}")
    _run_checked(
        argv,
        environment=environment,
        log=log,
        pass_fds=tuple(
            sorted({bag_fd, attestation_fd, *runtime_context.pass_fds})
        ),
        timeout_s=timeout_s,
        state_journal=state_journal,
        state_context=state_context,
        phase="CONSUMER_GUARD",
    )
    payload = json.loads(decision.read_text(encoding="utf-8"))
    if payload.get("contract_pass") is not True:
        raise AdapterViolation("backend consumer guard did not return contract PASS")
    return decision


def _run_process(
    argv: list[str],
    *,
    environment: Mapping[str, str],
    log: BinaryIO,
    timeout_s: int,
    pass_fds: tuple[int, ...],
    state_journal: Path | None = None,
    state_context: Mapping[str, Any] | None = None,
    phase: str = "PROCESS",
) -> tuple[int, bool]:
    context = dict(state_context or {})
    if state_journal is not None:
        common.append_hash_chain_jsonl(
            state_journal,
            {
                **context,
                "state": "PROCESS_LAUNCH_PENDING",
                "phase": phase,
                "argv_sha256": _argv_sha256(argv),
                "recorded_at": now(),
                "replay_boundary_may_be_crossed": phase == "REPLAY_ONLY",
            },
        )
    try:
        process = subprocess.Popen(
            argv,
            cwd=common.ROOT,
            env=dict(environment),
            stdout=log,
            stderr=subprocess.STDOUT,
            pass_fds=pass_fds,
            start_new_session=True,
        )
    except Exception as error:
        if state_journal is not None:
            common.append_hash_chain_jsonl(
                state_journal,
                {
                    **context,
                    "state": "PROCESS_LAUNCH_FAILED",
                    "phase": phase,
                    "argv_sha256": _argv_sha256(argv),
                    "error_type": type(error).__name__,
                    "recorded_at": now(),
                    "replay_boundary_may_be_crossed": phase == "REPLAY_ONLY",
                },
            )
        raise
    try:
        if state_journal is not None:
            common.append_hash_chain_jsonl(
                state_journal,
                {
                    **context,
                    "state": "PROCESS_STARTED",
                    "phase": phase,
                    "argv_sha256": _argv_sha256(argv),
                    "process_identity": common.process_identity(process.pid),
                    "recorded_at": now(),
                    "replay_boundary_may_be_crossed": phase == "REPLAY_ONLY",
                },
            )
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=15)
        raise
    try:
        returncode = process.wait(timeout=timeout_s)
        if state_journal is not None:
            common.append_hash_chain_jsonl(
                state_journal,
                {
                    **context,
                    "state": "PROCESS_EXITED",
                    "phase": phase,
                    "argv_sha256": _argv_sha256(argv),
                    "returncode": returncode,
                    "timed_out": False,
                    "recorded_at": now(),
                    "replay_boundary_may_be_crossed": phase == "REPLAY_ONLY",
                },
            )
        return returncode, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=15)
        if state_journal is not None:
            common.append_hash_chain_jsonl(
                state_journal,
                {
                    **context,
                    "state": "PROCESS_EXITED",
                    "phase": phase,
                    "argv_sha256": _argv_sha256(argv),
                    "returncode": 124,
                    "timed_out": True,
                    "recorded_at": now(),
                    "replay_boundary_may_be_crossed": phase == "REPLAY_ONLY",
                },
            )
        return 124, True


def execute_replay(
    row: Mapping[str, str],
    *,
    root: Path,
    attempt_dir: Path,
    lock_fd: int,
    run_dir_lease: common.DirectoryLease,
    job_authority: Mapping[str, str],
    execution_lock: Mapping[str, Any],
    runtime_context: common.RuntimeConsumptionContext,
    state_journal: Path,
    timeout_s: int,
    log: BinaryIO,
) -> dict[str, Any]:
    """Execute preparation and evaluator-free replay under the governed job."""
    common.validate_inherited_lock(lock_fd)
    common.validate_queue_row(row)
    if timeout_s <= 0:
        raise AdapterViolation("timeout must be positive")
    expected_attempt = common.output_path(
        root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    if common.lexical_absolute(attempt_dir) != expected_attempt or not attempt_dir.is_dir():
        raise AdapterViolation("adapter attempt directory is not the frozen job directory")
    run_dir = predicted_run_dir(row, root=root)
    if common.lexical_absolute(Path(run_dir_lease.path)) != run_dir:
        raise AdapterViolation("adapter run-directory lease differs from frozen queue")
    expected_state_journal = attempt_dir / "attempt_state_v1.jsonl"
    if common.lexical_absolute(state_journal) != common.lexical_absolute(
        expected_state_journal
    ):
        raise AdapterViolation("adapter state journal is outside the frozen attempt")
    authority_payload = validate_job_authority(
        row,
        root=root,
        attempt_dir=attempt_dir,
        lock_fd=lock_fd,
        run_dir_lease=run_dir_lease,
        authority=job_authority,
    )
    if (
        runtime_context.execution_lock_sha256
        != authority_payload.get("execution_lock_sha256")
    ):
        raise AdapterViolation("sealed runtime/job authority lock hash differs")
    snapshot = execution_lock.get("data_identity_snapshot")
    if not isinstance(snapshot, dict):
        raise AdapterViolation("adapter execution lock lacks data-identity snapshot")
    if authority_payload.get("data_identity_snapshot_hash") != snapshot.get(
        common.DATA_IDENTITY_SELF_HASH
    ):
        raise AdapterViolation("job authority data-identity snapshot binding drift")
    g0_authority = execution_lock.get(
        common.g0_governance.EXECUTION_LOCK_BINDING_KEY
    )
    if not isinstance(g0_authority, dict) or not isinstance(
        g0_authority.get("evaluation_lock"), dict
    ):
        raise AdapterViolation("adapter execution lock lacks G0 authority")
    if (
        authority_payload.get("g0_execution_authority_hash")
        != g0_authority.get("g0_execution_authority_hash")
        or authority_payload.get("g0_evaluation_lock_hash")
        != g0_authority["evaluation_lock"].get("evaluation_lock_hash")
    ):
        raise AdapterViolation("job authority G0 evaluation binding drift")
    state_context = {"queue_index": int(row["queue_index"]), "run_id": row["run_id"]}
    common.append_hash_chain_jsonl(
        state_journal,
        {
            **state_context,
            "state": "ADAPTER_ENTERED",
            "phase": "PRE_ADAPTER",
            "recorded_at": now(),
            "replay_boundary_may_be_crossed": False,
        },
    )
    data_identity_before = common.revalidate_data_identity_snapshot(
        root, snapshot, phase="ADAPTER_ENTRY"
    )
    common.write_json_exclusive(
        attempt_dir / "data_identity_adapter_before.json", data_identity_before
    )
    b0_entry: Mapping[str, Any] | None = None
    b0_play_path: Path | None = None
    b0_adapter_entry: dict[str, Any] | None = None
    if row["arm"] == common.B0_ARM:
        b0_entry = common.frozen_b0_play_input_for_row(execution_lock, row)
        path_identity = b0_entry.get("path_identity")
        if not isinstance(path_identity, dict):
            raise AdapterViolation("B0 frozen play input lacks path identity")
        b0_play_path = common.workspace_path(
            root, str(path_identity.get("path", "")), label="frozen B0 play input"
        )
        b0_adapter_entry = common.revalidate_b0_play_input(
            root,
            execution_lock,
            row,
            phase="ADAPTER_ENTRY",
            verify_sha256=False,
        )
        common.write_json_exclusive(
            attempt_dir / "b0_play_input_adapter_before.json", b0_adapter_entry
        )

    if row["arm"] == common.B0_ARM:
        input_report = input_checker.check_row_inputs(row, root=root)
        common.write_json_exclusive(attempt_dir / "input_check.json", input_report)
    prepare_argv = build_prepare_argv(
        row, root=root, runtime_context=runtime_context
    )
    config_argv = build_config_argv(
        row, root=root, runtime_context=runtime_context
    )
    if any(
        token in "\n".join(prepare_argv).lower()
        for token in (
            "run_isj_nativeq_contract_guarded",
            "run_p05_modern_xfeat_baseline_guarded",
            "run_isj_b1_klt_nativeq_guarded",
            "export_vins_features",
        )
    ):
        raise AdapterViolation("preparation argv contains a forbidden export wrapper")

    started = now()
    started_monotonic = time.monotonic()
    returncode: int | None = None
    timed_out = False
    error: Exception | None = None
    failure_stage: str | None = None
    replay_started = False
    preparation_completed = False
    config_completed = False
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    attestation_before: dict[str, Any] | None = None
    attestation_after: dict[str, Any] | None = None
    input_audit_before: dict[str, Any] | None = None
    input_audit_after: dict[str, Any] | None = None
    origin_play_bag_before: dict[str, Any] | None = None
    origin_play_bag_after: dict[str, Any] | None = None
    data_identity_pre_replay: dict[str, Any] | None = None
    data_identity_after: dict[str, Any] | None = None
    config_before: dict[str, Any] | None = None
    config_after: dict[str, Any] | None = None
    camera_config_before: dict[str, Any] | None = None
    camera_config_after: dict[str, Any] | None = None
    sealed_replay_config: dict[str, Any] | None = None
    consumer_decision: str | None = None
    consumer_feature_bag_sealed_readonly: bool | None = None
    replay_argv: list[str] | None = None

    def remaining_budget(label: str, maximum: int | None = None) -> int:
        remaining = timeout_s - (time.monotonic() - started_monotonic)
        if remaining <= 0:
            raise AdapterViolation(f"backend budget exhausted before {label}")
        seconds = max(1, math.ceil(remaining))
        return min(seconds, maximum) if maximum is not None else seconds

    def write_command(play_bag: str, vins_config_proc_path: str) -> list[str]:
        replay = build_backend_argv(
            row,
            root=root,
            play_bag=play_bag,
            frozen_b0_play_bag=b0_play_path,
            vins_config=vins_config_proc_path,
            runtime_context=runtime_context,
        )
        command_record: dict[str, Any] = {
            "schema_version": COMMAND_SCHEMA_VERSION,
            "queue_index": int(row["queue_index"]),
            "run_id": row["run_id"],
            "arm": row["arm"],
            "preparation_argv": prepare_argv,
            "preparation_argv_sha256": _argv_sha256(prepare_argv),
            "config_argv": config_argv,
            "config_argv_sha256": _argv_sha256(config_argv),
            "replay_argv": replay,
            "replay_argv_sha256": _argv_sha256(replay),
            # Compatibility alias: this is the only command that may start ROS/VINS.
            "argv": replay,
            "argv_sha256": _argv_sha256(replay),
            "expected_run_dir": common.display_path(root, run_dir),
            "vins_workspace": os.fspath(common.VINS_ORIGIN),
            "run_vins": True,
            "preparation_run_vins": False,
            "replay_only_runner": True,
            "evaluation_invoked": False,
            "force_export": False,
            "export_features": False,
            "feature_bag_path_disclosed_to_runner": False,
            "feature_bag_transport": (
                "none"
                if row["arm"] == common.B0_ARM
                else "sealed_memfd_byte_exact_copy"
            ),
            "vins_config_transport": "sealed_memfd_deterministic_camera_fd_binding",
            "sealed_vins_config": sealed_replay_config,
            "sealed_camera_config": camera_config_before,
            "started_at": started,
        }
        common.write_json_exclusive(attempt_dir / "adapter_command.json", command_record)
        return replay

    def pipeline(
        environment: Mapping[str, str],
        *,
        play_bag: str,
        pass_fds: tuple[int, ...],
    ) -> None:
        nonlocal returncode, timed_out, failure_stage, replay_started
        nonlocal preparation_completed, config_completed, replay_argv
        nonlocal origin_play_bag_before, origin_play_bag_after
        nonlocal config_before, config_after
        nonlocal camera_config_before, camera_config_after, sealed_replay_config
        nonlocal data_identity_pre_replay, data_identity_after
        inherited_fds = tuple(sorted({*pass_fds, *runtime_context.pass_fds}))
        assert_ros_port_available(int(environment["PORT"]))
        failure_stage = "PREPARATION"
        _run_required_phase(
            "preparation",
            prepare_argv,
            environment=environment,
            log=log,
            pass_fds=inherited_fds,
            timeout_s=remaining_budget("preparation"),
            state_journal=state_journal,
            state_context=state_context,
        )
        preparation_completed = True
        common.verify_directory_lease(run_dir_lease)
        failure_stage = "CONFIG_PREPARATION"
        _run_required_phase(
            "config preparation",
            config_argv,
            environment=environment,
            log=log,
            pass_fds=inherited_fds,
            timeout_s=remaining_budget("config preparation", maximum=120),
            state_journal=state_journal,
            state_context=state_context,
        )
        config_completed = True
        common.verify_directory_lease(run_dir_lease)
        _assert_pre_replay_boundary(run_dir)
        config_path = vins_config_path(row, root=root)
        camera_path = camera_config_path(row, root=root)
        config_snapshot = common.snapshot_regular_file(config_path)
        camera_snapshot = common.snapshot_regular_file(camera_path)
        with ExitStack() as config_stack:
            config_lease = config_stack.enter_context(
                common.SealedFileLease(
                    config_path,
                    config_snapshot.sha256,
                    role="generated_vins_config",
                    label="generated VINS config",
                    expected_size_bytes=config_snapshot.size_bytes,
                )
            )
            camera_lease = config_stack.enter_context(
                common.SealedFileLease(
                    camera_path,
                    camera_snapshot.sha256,
                    role="generated_camera_config",
                    label="generated camera config",
                    expected_size_bytes=camera_snapshot.size_bytes,
                )
            )
            if config_lease.fd is None or camera_lease.fd is None:
                raise AdapterViolation("generated config lease lacks an fd")
            original_config = os.pread(
                config_lease.fd, config_snapshot.size_bytes, 0
            )
            derived_config = _derived_replay_config_bytes(
                row,
                original=original_config,
                camera_name=camera_path.name,
                camera_proc_path=camera_lease.proc_path,
                root=root,
            )
            replay_config_lease = config_stack.enter_context(
                common.SealedBytesLease(
                    derived_config,
                    role="derived_replay_vins_config",
                    label="derived replay VINS config",
                )
            )
            if replay_config_lease.fd is None:
                raise AdapterViolation("derived replay config lease lacks an fd")
            config_before = config_lease.snapshot_dict()
            camera_config_before = camera_lease.snapshot_dict()
            sealed_replay_config = {
                "source_sha256": config_snapshot.sha256,
                "consumer_sha256": replay_config_lease.sha256,
                "size_bytes": replay_config_lease.size_bytes,
                "camera_source_sha256": camera_snapshot.sha256,
                "camera_transport": "sealed_memfd",
            }
            replay_argv = write_command(play_bag, replay_config_lease.proc_path)
            data_identity_pre_replay = common.revalidate_data_identity_snapshot(
                root, snapshot, phase="PRE_REPLAY_LAUNCH"
            )
            common.write_json_exclusive(
                attempt_dir / "data_identity_pre_replay.json",
                data_identity_pre_replay,
            )
            if row["arm"] == common.B0_ARM:
                origin_play_bag_before = common.revalidate_b0_play_input(
                    root, execution_lock, row, phase="PRE_REPLAY_LAUNCH"
                )
                common.write_json_exclusive(
                    attempt_dir / "b0_play_input_pre_replay.json",
                    origin_play_bag_before,
                )
            failure_stage = "REPLAY_ONLY"
            replay_started = True
            replay_fds = tuple(
                sorted(
                    {
                        *inherited_fds,
                        config_lease.fd,
                        camera_lease.fd,
                        replay_config_lease.fd,
                    }
                )
            )
            returncode, timed_out = _run_process(
                replay_argv,
                environment=environment,
                log=log,
                timeout_s=remaining_budget("replay-only runner"),
                pass_fds=replay_fds,
                state_journal=state_journal,
                state_context=state_context,
                phase="REPLAY_ONLY",
            )
            replay_config_lease.verify_sealed()
            config_after = config_lease.verify_unchanged().__dict__
            camera_config_after = camera_lease.verify_unchanged().__dict__
        if origin_play_bag_before is not None:
            origin_play_bag_after = common.revalidate_b0_play_input(
                root, execution_lock, row, phase="POST_REPLAY"
            )
            common.write_json_exclusive(
                attempt_dir / "b0_play_input_after.json", origin_play_bag_after
            )
        data_identity_after = common.revalidate_data_identity_snapshot(
            root, snapshot, phase="POST_REPLAY"
        )
        common.write_json_exclusive(
            attempt_dir / "data_identity_adapter_after.json", data_identity_after
        )
        common.verify_directory_lease(run_dir_lease)
        for name in ("ape.txt", "rpe.txt", "ape_rpe.json"):
            path = run_dir / name
            if path.exists() or path.is_symlink():
                raise AdapterViolation(
                    f"replay-only runner created forbidden evaluation artifact: {path}"
                )
        # Once the isolated replay process has started, frozen taxonomy owns
        # timeout/nonzero classification.  Preparation/config/port failures
        # above remain infrastructure and never consume an algorithmic slot.

    if row["arm"] == common.B0_ARM:
        try:
            if not isinstance(b0_entry, Mapping) or b0_play_path is None:
                raise AdapterViolation("B0 execution lacks its frozen play input")
            path_identity = b0_entry.get("path_identity")
            target_identity = (
                path_identity.get("resolved_target_identity")
                if isinstance(path_identity, Mapping)
                else None
            )
            expected_size = (
                int(target_identity["size_bytes"])
                if isinstance(target_identity, Mapping)
                and isinstance(target_identity.get("size_bytes"), int)
                else None
            )
            with common.SealedFileLease(
                b0_play_path,
                str(b0_entry.get("expected_sha256", "")),
                role="b0_play_input",
                label="B0 play input",
                expected_size_bytes=expected_size,
            ) as b0_lease:
                if b0_lease.fd is None:
                    raise AdapterViolation("B0 sealed play input lacks an fd")
                environment = safe_environment(
                    row,
                    root=root,
                    attempt_dir=attempt_dir,
                    feature_bag_fd_path=None,
                    b0_play_input_path=b0_lease.proc_path,
                    preparation_bag_fd_path=b0_lease.proc_path,
                    runtime_context=runtime_context,
                )
                try:
                    pipeline(
                        environment,
                        play_bag=b0_lease.proc_path,
                        pass_fds=(b0_lease.fd,),
                    )
                finally:
                    b0_lease.verify_unchanged()
        except Exception as caught:
            error = caught
    else:
        bag_path = common.workspace_path(root, row["feature_bag"], label="feature bag")
        attestation_path = common.workspace_path(
            root, row["attestation_path"], label="attestation"
        )
        input_audit_path = common.workspace_path(
            root, row["input_audit_path"], label="input audit"
        )
        try:
            preparation_path = prematerialized_preparation_bag(row, root=root)
            preparation_snapshot = common.snapshot_regular_file(preparation_path)
            with ExitStack() as input_stack:
                feature_lease = input_stack.enter_context(
                    common.SealedFileLease(
                        bag_path,
                        row["feature_bag_sha256"],
                        role="feature_bag",
                        label="feature bag",
                    )
                )
                attestation_lease = input_stack.enter_context(
                    common.SealedFileLease(
                        attestation_path,
                        row["attestation_sha256"],
                        role="feature_attestation",
                        label="feature attestation",
                    )
                )
                audit_lease = input_stack.enter_context(
                    common.SealedFileLease(
                        input_audit_path,
                        row["input_audit_sha256"],
                        role="feature_input_audit",
                        label="feature input audit",
                    )
                )
                preparation_lease = input_stack.enter_context(
                    common.SealedFileLease(
                        preparation_path,
                        preparation_snapshot.sha256,
                        role="prematerialized_preparation_bag",
                        label="pre-materialized preparation bag",
                        expected_size_bytes=preparation_snapshot.size_bytes,
                    )
                )
                leases = (
                    feature_lease,
                    attestation_lease,
                    audit_lease,
                    preparation_lease,
                )
                if any(lease.fd is None for lease in leases):
                    raise AdapterViolation("sealed replay input unexpectedly lacks an fd")
                before = feature_lease.snapshot_dict()
                attestation_before = attestation_lease.snapshot_dict()
                input_audit_before = audit_lease.snapshot_dict()
                consumer_feature_bag_sealed_readonly = True
                input_report = input_checker.check_row_inputs(
                    row,
                    root=root,
                    bag_path_override=Path(feature_lease.proc_path),
                    attestation_path_override=Path(attestation_lease.proc_path),
                    input_audit_path_override=Path(audit_lease.proc_path),
                )
                common.write_json_exclusive(
                    attempt_dir / "input_check.json", input_report
                )
                environment = safe_environment(
                    row,
                    root=root,
                    attempt_dir=attempt_dir,
                    feature_bag_fd_path=feature_lease.proc_path,
                    preparation_bag_fd_path=preparation_lease.proc_path,
                    runtime_context=runtime_context,
                )
                try:
                    assert_ros_port_available(int(environment["PORT"]))
                    decision = run_consumer_guard(
                        row,
                        root=root,
                        attempt_dir=attempt_dir,
                        environment=environment,
                        bag_proc_path=feature_lease.proc_path,
                        attestation_proc_path=attestation_lease.proc_path,
                        bag_fd=int(feature_lease.fd),
                        attestation_fd=int(attestation_lease.fd),
                        runtime_context=runtime_context,
                        log=log,
                        timeout_s=remaining_budget("consumer guard", maximum=300),
                        state_journal=state_journal,
                        state_context=state_context,
                    )
                    consumer_decision = common.display_path(root, decision)
                    pipeline(
                        environment,
                        play_bag=feature_lease.proc_path,
                        pass_fds=tuple(int(lease.fd) for lease in leases),
                    )
                except Exception as caught:
                    error = caught
                finally:
                    try:
                        after = feature_lease.verify_unchanged().__dict__
                        attestation_after = (
                            attestation_lease.verify_unchanged().__dict__
                        )
                        input_audit_after = audit_lease.verify_unchanged().__dict__
                        preparation_lease.verify_unchanged()
                    except Exception as mutation:
                        consumer_feature_bag_sealed_readonly = False
                        error = mutation
        except Exception as caught:
            error = caught

    try:
        common.verify_directory_lease(run_dir_lease)
    except Exception as mutation:
        error = mutation

    feature_input_unchanged = row["arm"] == common.B0_ARM or (
        before is not None
        and after is not None
        and before == after
        and attestation_before is not None
        and attestation_before == attestation_after
        and input_audit_before is not None
        and input_audit_before == input_audit_after
    )
    origin_input_unchanged = row["arm"] != common.B0_ARM or (
        origin_play_bag_before is not None
        and origin_play_bag_after is not None
        and origin_play_bag_before.get("play_input_id")
        == origin_play_bag_after.get("play_input_id")
        and origin_play_bag_before.get("path_identity")
        == origin_play_bag_after.get("path_identity")
        and origin_play_bag_before.get("derivation_hash")
        == origin_play_bag_after.get("derivation_hash")
    )
    input_unchanged = feature_input_unchanged and origin_input_unchanged
    data_identity_unchanged = (
        data_identity_before is not None
        and data_identity_pre_replay is not None
        and (not replay_started or data_identity_after is not None)
    )
    input_unchanged = input_unchanged and data_identity_unchanged
    if not input_unchanged:
        status = "FAIL_INPUT_IMMUTABILITY"
    elif error is not None:
        status = "FAIL_GOVERNANCE"
    elif returncode == 0 and not timed_out:
        status = "PASS_EXECUTION_ENVELOPE"
    else:
        status = "TERMINAL_PROCESS_FAILURE"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
        "returncode": returncode,
        "timed_out": timed_out,
        "failure_stage": failure_stage,
        "replay_started": replay_started,
        "preparation_completed": preparation_completed,
        "config_completed": config_completed,
        "started_at": started,
        "finished_at": now(),
        "elapsed_s": time.monotonic() - started_monotonic,
        "expected_run_dir": common.display_path(root, run_dir),
        "input_feature_bag_before": before,
        "input_feature_bag_after": after,
        "input_attestation_before": attestation_before,
        "input_attestation_after": attestation_after,
        "input_audit_before": input_audit_before,
        "input_audit_after": input_audit_after,
        "origin_play_bag_before": origin_play_bag_before,
        "origin_play_bag_after": origin_play_bag_after,
        "data_identity_before": data_identity_before,
        "data_identity_pre_replay": data_identity_pre_replay,
        "data_identity_after": data_identity_after,
        "data_identity_unchanged": data_identity_unchanged,
        "vins_config_before": config_before,
        "vins_config_after": config_after,
        "camera_config_before": camera_config_before,
        "camera_config_after": camera_config_after,
        "sealed_replay_config": sealed_replay_config,
        "input_feature_bag_unchanged": input_unchanged,
        "consumer_feature_bag_sealed_readonly": consumer_feature_bag_sealed_readonly,
        "backend_consumer_contract_decision": consumer_decision,
        "error_type": type(error).__name__ if error is not None else None,
        "error": str(error) if error is not None else None,
        "trajectory_metrics_read_by_adapter": False,
        "evaluation_invoked": False,
        "ape_rpe_artifacts_created": False,
        "export_wrapper_invoked": False,
        "preparation_runner_invoked_with_run_vins_zero": preparation_completed,
        "replay_only_runner_invoked": replay_started,
        "direct_eval_runner_used_for_replay": False,
        "backend_replay_manifest": common.display_path(
            root, run_dir / "backend_replay_manifest.txt"
        ),
    }
    common.write_json_exclusive(attempt_dir / "adapter_result.json", result)
    return result


def main() -> int:
    # Direct adapter execution would bypass capacity, no-clobber registry, and
    # the terminal auditor.  Keep this file import-only for formal P07 work.
    print(
        "P07_BACKEND_ADAPTER_DIRECT_CLI_FORBIDDEN: use "
        "scripts/run_p07_backend_replay_job_v1.py",
        file=os.sys.stderr,
    )
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
