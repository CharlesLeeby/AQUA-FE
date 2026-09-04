#!/usr/bin/env python3
"""Seal the successful r3 probe16 contract as a formal900 adoption permit.

This builder never runs a detector, producer, pair auditor, or VINS process.
It holds the complete r3 evidence tree open while validating the immutable
freeze/start/PASS-seal and one-shot launcher chains.  The resulting permit
contains identities and an outcome-blind static projection digest, never
relative arm metrics or an observed winner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import audit_matched_birth_rawlk_pair_v1 as probe_audit
from scripts import run_matched_birth_arm_once_v1 as launcher


SCHEMA_VERSION = "aqua-fe-detector-birth-rawlk-formal900-adoption-v1"
STATUS = "ADOPTED_R3_PASS_FOR_FRESH_FORMAL900_FREEZE_ONLY"
SCIENTIFIC_ROLE = "POST_PROBE_CONTRACT_PASS_GATED_FORMAL_SCALE_PROMOTION"
R3_ROOT = WORKSPACE_ROOT / "experiments/matched_birth_a02_4500_6300_r3"
R4_ROOT = (
    WORKSPACE_ROOT
    / "experiments/matched_birth_a02_4500_6300_formal900_r4"
)
DEFAULT_OUTPUT = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_r3_pass_formal900_adoption_v1.json"
)
HUMAN_RECORD = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_r3_pass_formal900_adoption_v1.md"
)
PY_CACHE_PREFIX = Path(
    "/tmp/aqua-fe-a02-matched-birth-rawlk-empty-pycache-v1"
)
ROOT_FILES = frozenset(
    {
        "probe16_freeze.json",
        "probe16_pre_run_start_receipt.json",
        "probe16_post_run_pair_seal.json",
    }
)
ARM_FILES = frozenset(
    {
        "command_contract.json",
        "producer_attempt.json",
        "launcher_start_receipt.json",
        "launcher_rc_receipt.json",
        "export_manifest.json",
        "features.bag",
        "raw_diagnostics.csv",
        "legacy_primitive_manifest.json",
    }
)
ARM_DIRECTORIES = {
    probe_audit.XFEAT_ARM: "xfeat_r3",
    probe_audit.GFTT_ARM: "gftt_r3",
}
EXPECTED_R3_COMMIT_IDENTITIES = {
    "freeze": {
        "path": str(R3_ROOT / "probe16_freeze.json"),
        "size_bytes": 648465,
        "sha256": "91276272a93fc1e8814e261733ab4ffc2ceed268ad3fedde2197b96a4801aaa3",
    },
    "pre_run_start_receipt": {
        "path": str(R3_ROOT / "probe16_pre_run_start_receipt.json"),
        "size_bytes": 9091,
        "sha256": "3847f0de5ff511e0716180efb900dd6563f3bbfe8fd85e28ce0432bfef5a2a7d",
    },
    "post_run_pair_seal": {
        "path": str(R3_ROOT / "probe16_post_run_pair_seal.json"),
        "size_bytes": 109803,
        "sha256": "b27126c34976720c36904cba6e9478ff66efa4d1bb0f3c981a7d667e8752edcd",
    },
}
EXPECTED_GATE_NAMES = frozenset(
    {
        "freeze_and_locked_inputs",
        "gftt_diagnostics_manifest_csv_raw_binding",
        "gftt_feature_contract",
        "gftt_legacy_transport_evidence",
        "independent_raw_reconstruction",
        "manifest_pair",
        "nonfeature_exact",
        "one_shot_launcher_receipts",
        "processed_image_and_schedule_pair",
        "xfeat_diagnostics_manifest_csv_raw_binding",
        "xfeat_feature_contract",
        "xfeat_legacy_transport_evidence",
    }
)
EXPECTED_CLAIM_BOUNDARY = {
    "confirmatory": False,
    "detector_birth_source_only_within_this_frozen_carrier": True,
    "statistical_significance": False,
    "whole_slam_superiority": False,
}
EXPECTED_R3_DEVICE_ID = 66312


class AdoptionError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _strict_equal(actual: object, expected: object, *, label: str) -> None:
    if type(actual) is not type(expected) or _canonical_bytes(actual) != _canonical_bytes(
        expected
    ):
        raise AdoptionError(f"{label} mismatch")


def _exact_keys(value: object, keys: set[str], *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise AdoptionError(f"{label} keyset mismatch")
    return value


def _identity(path: Path, payload: bytes) -> dict[str, object]:
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _read_fd(fd: int, expected: tuple[int, int], *, label: str) -> tuple[bytes, os.stat_result]:
    before = os.fstat(fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or int(before.st_nlink) != 1
        or (int(before.st_dev), int(before.st_ino)) != expected
    ):
        raise AdoptionError(f"{label} is not the held single-link regular inode")
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(fd)
    if (
        (int(after.st_dev), int(after.st_ino)) != expected
        or int(after.st_size) != sum(len(chunk) for chunk in chunks)
        or int(after.st_mtime_ns) != int(before.st_mtime_ns)
        or int(after.st_ctime_ns) != int(before.st_ctime_ns)
    ):
        raise AdoptionError(f"{label} changed during held read")
    return b"".join(chunks), after


def _decode_json(path: Path, payload: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdoptionError(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise AdoptionError(f"{label} is not a JSON object")
    expected = (
        (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if path.name == "legacy_primitive_manifest.json"
        else _canonical_bytes(value)
    )
    if payload != expected:
        raise AdoptionError(f"{label} canonical codec mismatch")
    return value


def _open_directory(
    path: Path,
    *,
    name: str | None,
    parent_fd: int | None,
    descriptors: dict[Path, int],
) -> int:
    lexical = str(path) if name is None else name
    visible = (
        os.lstat(path)
        if parent_fd is None
        else os.stat(lexical, dir_fd=parent_fd, follow_symlinks=False)
    )
    fd = os.open(
        lexical,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    held = os.fstat(fd)
    if (
        stat.S_ISLNK(visible.st_mode)
        or not stat.S_ISDIR(held.st_mode)
        or (int(visible.st_dev), int(visible.st_ino))
        != (int(held.st_dev), int(held.st_ino))
        or int(held.st_uid) != int(os.getuid())
        or stat.S_IMODE(held.st_mode) != 0o700
    ):
        os.close(fd)
        raise AdoptionError(f"r3 directory identity/mode drift: {path}")
    descriptors[path] = fd
    return fd


def _open_file(
    path: Path,
    *,
    name: str,
    parent_fd: int,
    descriptors: dict[Path, int],
    payloads: dict[Path, bytes],
) -> None:
    visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    fd = os.open(
        name,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    # Register immediately after O_NOFOLLOW open so every subsequent failure
    # is covered by this local cleanup path and the outer snapshot lifecycle.
    descriptors[path] = fd
    try:
        held = os.fstat(fd)
        identity = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or identity != (int(visible.st_dev), int(visible.st_ino))
            or int(held.st_uid) != int(os.getuid())
        ):
            raise AdoptionError(f"r3 file open race/owner drift: {path}")
        payload, final_stat = _read_fd(fd, identity, label=f"r3 {path.name}")
        required_mode = 0o444 if path.name in {
            "probe16_freeze.json",
            "probe16_pre_run_start_receipt.json",
            "probe16_post_run_pair_seal.json",
            "command_contract.json",
            "producer_attempt.json",
            "launcher_start_receipt.json",
            "launcher_rc_receipt.json",
        } else 0o664
        if stat.S_IMODE(final_stat.st_mode) != required_mode:
            raise AdoptionError(f"r3 file mode drift: {path}")
        payloads[path] = payload
    except BaseException:
        descriptors.pop(path, None)
        os.close(fd)
        raise


def _directory_row(path: Path, fd: int) -> dict[str, object]:
    observed = os.fstat(fd)
    return {
        "path": str(path),
        "kind": "directory",
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
        "uid": int(observed.st_uid),
        "gid": int(observed.st_gid),
        "device_id": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "nlink": int(observed.st_nlink),
        "size_bytes": int(observed.st_size),
    }


def _file_row(path: Path, fd: int, payload: bytes) -> dict[str, object]:
    observed = os.fstat(fd)
    return {
        "path": str(path),
        "kind": "regular",
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
        "uid": int(observed.st_uid),
        "gid": int(observed.st_gid),
        "device_id": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "nlink": int(observed.st_nlink),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _snapshot_r3() -> dict[str, object]:
    if R3_ROOT.expanduser().absolute() != R3_ROOT or R3_ROOT.resolve(strict=True) != R3_ROOT:
        raise AdoptionError("r3 root is not canonical and symlink-free")
    directories: dict[Path, int] = {}
    files: dict[Path, int] = {}
    payloads: dict[Path, bytes] = {}
    try:
        root_fd = _open_directory(
            R3_ROOT, name=None, parent_fd=None, descriptors=directories
        )
        if int(os.fstat(root_fd).st_dev) != EXPECTED_R3_DEVICE_ID:
            raise AdoptionError("r3 root device identity drift")
        if probe_audit._fstatfs_magic(root_fd) != probe_audit.EXT4_SUPER_MAGIC:
            raise AdoptionError("r3 root is not on the frozen ext4 filesystem class")
        expected_root = ROOT_FILES | {"xfeat_r3", "gftt_r3"}
        if set(os.listdir(root_fd)) != expected_root:
            raise AdoptionError("r3 root exact listing drift")
        for arm_name in ("xfeat_r3", "gftt_r3"):
            arm_path = R3_ROOT / arm_name
            arm_fd = _open_directory(
                arm_path, name=arm_name, parent_fd=root_fd,
                descriptors=directories,
            )
            if set(os.listdir(arm_fd)) != ARM_FILES | {"private_work"}:
                raise AdoptionError(f"r3 {arm_name} exact listing drift")
            private_path = arm_path / "private_work"
            private_fd = _open_directory(
                private_path, name="private_work", parent_fd=arm_fd,
                descriptors=directories,
            )
            if os.listdir(private_fd):
                raise AdoptionError(f"r3 {arm_name} private work is not empty")
        for name in sorted(ROOT_FILES):
            _open_file(
                R3_ROOT / name, name=name, parent_fd=root_fd,
                descriptors=files, payloads=payloads,
            )
        for arm_name in ("xfeat_r3", "gftt_r3"):
            arm_path = R3_ROOT / arm_name
            arm_fd = directories[arm_path]
            for name in sorted(ARM_FILES):
                _open_file(
                    arm_path / name, name=name, parent_fd=arm_fd,
                    descriptors=files, payloads=payloads,
                )
        rows = [
            *(_directory_row(path, fd) for path, fd in directories.items()),
            *(_file_row(path, fd, payloads[path]) for path, fd in files.items()),
        ]
        rows.sort(key=lambda row: str(row["path"]))
        if (
            len(directories) != 5
            or len(files) != 19
            or len(rows) != 24
            or len({row["path"] for row in rows}) != 24
            or {int(row["device_id"]) for row in rows}
            != {EXPECTED_R3_DEVICE_ID}
        ):
            raise AdoptionError("r3 tree is not exact 5 directories plus 19 files")
        return {
            "directories": directories,
            "files": files,
            "payloads": payloads,
            "inventory": rows,
        }
    except BaseException:
        for fd in list(files.values()) + list(reversed(tuple(directories.values()))):
            os.close(fd)
        raise


def _finish_snapshot(snapshot: Mapping[str, object]) -> None:
    directories = snapshot["directories"]
    files = snapshot["files"]
    payloads = snapshot["payloads"]
    root_fd = directories[R3_ROOT]
    if set(os.listdir(root_fd)) != ROOT_FILES | {"xfeat_r3", "gftt_r3"}:
        raise AdoptionError("r3 root changed before snapshot close")
    for arm_name in ("xfeat_r3", "gftt_r3"):
        arm = R3_ROOT / arm_name
        if set(os.listdir(directories[arm])) != ARM_FILES | {"private_work"}:
            raise AdoptionError(f"r3 {arm_name} changed before snapshot close")
        if os.listdir(directories[arm / "private_work"]):
            raise AdoptionError(f"r3 {arm_name} private work changed")
    final_rows = [
        _directory_row(path, fd) for path, fd in directories.items()
    ]
    for path, fd in files.items():
        held = os.fstat(fd)
        payload, final_stat = _read_fd(
            fd, (int(held.st_dev), int(held.st_ino)), label=f"final r3 {path.name}"
        )
        if payload != payloads[path]:
            raise AdoptionError(f"r3 held bytes changed: {path}")
        final_rows.append(
            {
                "path": str(path), "kind": "regular",
                "mode_octal": format(stat.S_IMODE(final_stat.st_mode), "04o"),
                "uid": int(final_stat.st_uid), "gid": int(final_stat.st_gid),
                "device_id": int(final_stat.st_dev),
                "inode": int(final_stat.st_ino), "nlink": int(final_stat.st_nlink),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    final_rows.sort(key=lambda row: str(row["path"]))
    _strict_equal(final_rows, snapshot["inventory"], label="r3 final held inventory")
    for path, fd in {**directories, **files}.items():
        visible = os.lstat(path)
        held = os.fstat(fd)
        if (
            stat.S_ISLNK(visible.st_mode)
            or (int(visible.st_dev), int(visible.st_ino))
            != (int(held.st_dev), int(held.st_ino))
        ):
            raise AdoptionError(f"r3 visible inode drift at close: {path}")


def _close_snapshot(snapshot: Mapping[str, object]) -> None:
    for fd in list(snapshot["files"].values()) + list(
        reversed(tuple(snapshot["directories"].values()))
    ):
        os.close(fd)


def _validate_and_build_record() -> dict[str, object]:
    if Path.cwd() != WORKSPACE_ROOT:
        raise AdoptionError("adoption builder cwd is not the frozen workspace root")
    try:
        builder_runtime = probe_audit._audit_runtime_observation()
    except probe_audit.AuditFailure as exc:
        raise AdoptionError(f"adoption builder runtime drift: {exc}") from exc
    if os.path.lexists(R4_ROOT):
        raise AdoptionError("fresh r4 target root already exists")
    if os.path.lexists(PY_CACHE_PREFIX):
        raise AdoptionError("shared frozen pycache prefix is not absent")
    snapshot = _snapshot_r3()
    try:
        payloads = snapshot["payloads"]
        rows_by_path = {row["path"]: row for row in snapshot["inventory"]}

        def data(path: Path) -> bytes:
            value = payloads.get(path)
            if type(value) is not bytes:
                raise AdoptionError(f"r3 held payload missing: {path}")
            return value

        def object_at(path: Path) -> dict[str, object]:
            return _decode_json(path, data(path), label=f"r3 {path.name}")

        def identity_at(path: Path) -> dict[str, object]:
            return _identity(path, data(path))

        freeze_path = R3_ROOT / "probe16_freeze.json"
        start_path = R3_ROOT / "probe16_pre_run_start_receipt.json"
        seal_path = R3_ROOT / "probe16_post_run_pair_seal.json"
        freeze = object_at(freeze_path)
        start = object_at(start_path)
        seal = object_at(seal_path)
        commit_identities = {
            "freeze": identity_at(freeze_path),
            "pre_run_start_receipt": identity_at(start_path),
            "post_run_pair_seal": identity_at(seal_path),
        }
        _strict_equal(
            commit_identities, EXPECTED_R3_COMMIT_IDENTITIES,
            label="r3 immutable commit identities",
        )
        if (
            freeze.get("schema_version") != probe_audit.FREEZE_SCHEMA_VERSION
            or freeze.get("status") != "FROZEN"
            or freeze.get("fixed_semantics", {}).get("allow_prefix_nonformal") is not True
            or freeze.get("fixed_semantics", {}).get("expected_published_frames") != 16
            or freeze.get("fixed_semantics", {}).get("expected_raw_frames") != 32
        ):
            raise AdoptionError("r3 freeze is not the exact probe16 mode")
        if (
            start.get("schema_version") != probe_audit.SCHEMA_VERSION
            or start.get("status") != "PASS_PRE_RUN_FREEZE_AND_ABSENCE"
            or start.get("pass") is not True
        ):
            raise AdoptionError("r3 pre-run start receipt did not pass")
        _strict_equal(
            start.get("pre_run_freeze"), commit_identities["freeze"],
            label="r3 start-to-freeze binding",
        )
        if (
            seal.get("schema_version") != probe_audit.SCHEMA_VERSION
            or seal.get("status") != "PASS"
            or seal.get("pass") is not True
            or seal.get("allow_prefix_nonformal") is not True
            or seal.get("expected_published_frames") != 16
        ):
            raise AdoptionError("r3 pair seal is not an exact probe16 PASS")
        _strict_equal(
            seal.get("claim_boundary"), EXPECTED_CLAIM_BOUNDARY,
            label="r3 claim boundary",
        )
        gates = _exact_keys(
            seal.get("gates"), set(EXPECTED_GATE_NAMES), label="r3 seal gates"
        )
        if any(type(gates[name]) is not dict or gates[name].get("pass") is not True for name in gates):
            raise AdoptionError("not every r3 contract gate passed")
        outcome_seal = _exact_keys(
            seal.get("post_run_outcome_seal"),
            {"pre_run_freeze", "pre_run_start_receipt", "arms"},
            label="r3 post-run outcome seal",
        )
        _strict_equal(
            outcome_seal["pre_run_freeze"], commit_identities["freeze"],
            label="r3 seal-to-freeze binding",
        )
        _strict_equal(
            outcome_seal["pre_run_start_receipt"],
            commit_identities["pre_run_start_receipt"],
            label="r3 seal-to-start binding",
        )
        contracts: dict[str, dict[str, object]] = {}
        receipts: dict[str, dict[str, object]] = {}
        role_bindings: dict[str, object] = {
            "freeze": commit_identities["freeze"],
            "pre_run_start_receipt": commit_identities["pre_run_start_receipt"],
            "post_run_pair_seal": commit_identities["post_run_pair_seal"],
            "arms": {},
        }
        process_qualification: dict[str, object] = {}
        sealed_arms = _exact_keys(
            outcome_seal["arms"], set(ARM_DIRECTORIES), label="r3 sealed arms"
        )
        for arm_id, arm_name in ARM_DIRECTORIES.items():
            directory = R3_ROOT / arm_name
            paths = {
                "command_contract": directory / "command_contract.json",
                "attempt": directory / "producer_attempt.json",
                "launcher_start_receipt": directory / "launcher_start_receipt.json",
                "launcher_rc_receipt": directory / "launcher_rc_receipt.json",
                "manifest": directory / "export_manifest.json",
                "feature_bag": directory / "features.bag",
                "diagnostics": directory / "raw_diagnostics.csv",
                "legacy_primitive_manifest": directory / "legacy_primitive_manifest.json",
            }
            identities = {role: identity_at(path) for role, path in paths.items()}
            role_bindings["arms"][arm_id] = identities
            sealed = _exact_keys(
                sealed_arms[arm_id],
                {
                    "attempt", "diagnostics", "feature_bag",
                    "launcher_rc_receipt", "launcher_start_receipt",
                    "legacy_primitive_manifest", "manifest",
                },
                label=f"r3 {arm_id} sealed role identities",
            )
            for role in sealed:
                _strict_equal(
                    sealed[role], identities[role],
                    label=f"r3 {arm_id} sealed {role}",
                )
            contracts[arm_id] = object_at(paths["command_contract"])
            attempt = object_at(paths["attempt"])
            start_receipt = object_at(paths["launcher_start_receipt"])
            rc = object_at(paths["launcher_rc_receipt"])
            manifest = object_at(paths["manifest"])
            legacy = object_at(paths["legacy_primitive_manifest"])
            _strict_equal(
                freeze["authoritative_commands"]["arms"][arm_id]["command_contract"],
                identities["command_contract"],
                label=f"r3 {arm_id} freeze command identity",
            )
            _strict_equal(
                rc.get("start_receipt"), identities["launcher_start_receipt"],
                label=f"r3 {arm_id} RC-to-start",
            )
            _strict_equal(
                rc.get("command_contract"), identities["command_contract"],
                label=f"r3 {arm_id} RC-to-command",
            )
            _strict_equal(
                manifest.get("attempt"),
                {"identity": identities["attempt"], "payload": attempt},
                label=f"r3 {arm_id} manifest attempt",
            )
            expected_outputs = {
                "feature_bag": identities["feature_bag"],
                "raw_diagnostics_csv": identities["diagnostics"],
                "legacy_primitive_manifest": identities["legacy_primitive_manifest"],
            }
            _strict_equal(
                manifest.get("outputs"), expected_outputs,
                label=f"r3 {arm_id} manifest outputs",
            )
            legacy_output = legacy.get("output_bag")
            if type(legacy_output) is not dict:
                raise AdoptionError(f"r3 {arm_id} legacy output malformed")
            _strict_equal(
                {key: legacy_output.get(key) for key in ("size_bytes", "sha256")},
                {key: identities["feature_bag"][key] for key in ("size_bytes", "sha256")},
                label=f"r3 {arm_id} legacy output bytes",
            )
            if (
                manifest.get("status") != "PREFIX_NONFORMAL"
                or manifest.get("formal_eligible") is not False
                or manifest.get("formal_eligibility_reason")
                != "explicit_prefix_is_nonformal"
                or legacy.get("formal_eligibility_reason")
                != "explicit_prefix_is_nonformal"
                or attempt.get("attempt_count") != 1
                or attempt.get("process_start_count") != 1
                or attempt.get("no_retry") is not True
                or attempt.get("prefix_nonformal") is not True
            ):
                raise AdoptionError(f"r3 {arm_id} prefix/attempt contract drift")
            process = rc.get("producer_process")
            if type(process) is not dict:
                raise AdoptionError(f"r3 {arm_id} producer process malformed")
            expected_process = {
                "launch_attempt_count": 1,
                "process_start_count": 1,
                "producer_return_code": 0,
                "natural_end_observed": True,
                "exited_normally": True,
                "terminated_by_signal": False,
                "signal_number": None,
                "supervisor_sent_signal": False,
                "timed_out": False,
                "timeout_seconds": None,
                "retry_performed": False,
            }
            for key, expected in expected_process.items():
                _strict_equal(
                    process.get(key), expected,
                    label=f"r3 {arm_id} producer {key}",
                )
            process_qualification[arm_id] = expected_process
            start_row = rows_by_path[str(paths["launcher_start_receipt"])]
            rc_row = rows_by_path[str(paths["launcher_rc_receipt"])]
            receipts[arm_id] = {
                "start": start_receipt,
                "rc": rc,
                "start_identity": identities["launcher_start_receipt"],
                "rc_identity": identities["launcher_rc_receipt"],
                "start_mode": int(str(start_row["mode_octal"]), 8),
                "rc_mode": int(str(rc_row["mode_octal"]), 8),
            }

        arm_paths = {
            arm_id: {
                role: Path(value)
                for role, value in freeze["arms"][arm_id]["paths"].items()
            }
            for arm_id in ARM_DIRECTORIES
        }
        audit_paths = {
            role: Path(value) for role, value in freeze["audit_paths"].items()
        }
        governance = probe_audit._validate_governance_contract(
            freeze,
            freeze_json=freeze_path,
            source_bag=Path(freeze["locked_inputs"]["source_feature_bag"]["path"]),
            raw_bag=Path(freeze["locked_inputs"]["raw_image_bag"]["path"]),
            camera_yaml=Path(freeze["locked_inputs"]["camera_yaml"]["path"]),
            arm_paths=arm_paths,
            audit_paths=audit_paths,
            feature_topic=probe_audit.FEATURE_TOPIC_DEFAULT,
            image_topic="/camera/image_raw",
            allow_prefix=True,
            expected_frames=16,
            in_memory_command_contracts=contracts,
        )
        probe_audit._validate_launcher_receipts(
            {"governance": governance},
            in_memory_receipts=receipts,
            in_memory_command_contracts=contracts,
        )
        projection = probe_audit._continuation_scientific_projection(
            freeze, command_contracts=contracts
        )
        projection_sha = hashlib.sha256(_canonical_bytes(projection)).hexdigest()
        _finish_snapshot(snapshot)
        human_payload, human_stat = probe_audit._read_regular_nofollow(
            HUMAN_RECORD, label="human adoption record"
        )
        if (
            stat.S_ISLNK(human_stat.st_mode)
            or not stat.S_ISREG(human_stat.st_mode)
            or int(human_stat.st_nlink) != 1
            or int(human_stat.st_uid) != int(os.getuid())
            or stat.S_IMODE(human_stat.st_mode) != 0o444
        ):
            raise AdoptionError("human adoption record is not sealed 0444 evidence")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "scientific_role": SCIENTIFIC_ROLE,
            "builder_identity": probe_audit._file_identity(
                Path(__file__), label="r3 formal900 adoption builder"
            ),
            "builder_execution_contract": {
                "working_directory": str(WORKSPACE_ROOT),
                "environment": dict(launcher.FROZEN_ENVIRONMENT),
                "authorized_write_once_argv": [
                    "/usr/bin/python3.8", "-B", "-m",
                    "scripts.build_matched_birth_r3_pass_formal900_adoption_v1",
                    "--action", "write-once", "--output", str(DEFAULT_OUTPUT),
                ],
                "runtime": builder_runtime,
                "runtime_sha256": probe_audit.core._canonical_sha256(
                    builder_runtime
                ),
            },
            "human_record": _identity(HUMAN_RECORD, human_payload),
            "source_namespace": {
                "root": str(R3_ROOT),
                "filesystem": {
                    "filesystem_type": "ext4",
                    "device_id": EXPECTED_R3_DEVICE_ID,
                },
                "tree_entry_count": 24,
                "directory_count": 5,
                "regular_file_count": 19,
                "exact_tree_inventory": snapshot["inventory"],
                "role_bindings": role_bindings,
            },
            "pass_qualification": {
                "freeze_status": "FROZEN",
                "start_status": "PASS_PRE_RUN_FREEZE_AND_ABSENCE",
                "seal_status": "PASS",
                "seal_pass": True,
                "required_gate_names": sorted(EXPECTED_GATE_NAMES),
                "every_gate_pass": True,
                "per_arm_process": process_qualification,
            },
            "source_static_projection_sha256": projection_sha,
            "target": {
                "root": str(R4_ROOT),
                "arm_directories": {"xfeat": "xfeat_r4", "gftt": "gftt_r4"},
                "mode": "formal900",
                "allow_prefix_nonformal": False,
                "published_frames": 900,
                "raw_frames": 1800,
            },
            "formal_transition_contract": {
                "transform_id": "probe16_to_formal900_v1",
                "path_mapping": {
                    str(R3_ROOT): str(R4_ROOT),
                    str(R3_ROOT / "xfeat_r3"): str(R4_ROOT / "xfeat_r4"),
                    str(R3_ROOT / "gftt_r3"): str(R4_ROOT / "gftt_r4"),
                },
                "mode_transition": {
                    "allow_prefix_nonformal": [True, False],
                    "published_frames": [16, 900],
                    "raw_frames": [32, 1800],
                },
                "producer_argv_transition": {
                    "remove_exact_terminal_suffix": [
                        "--max-published-frames", "16"
                    ],
                    "replacement_limit_flag_forbidden": True,
                },
            },
            "evidence_use_boundary": {
                "source_output_bytes_read_for_integrity": True,
                "source_contract_pass_used_for_promotion": True,
                "source_relative_metrics_used_for_target_configuration": False,
                "source_output_bytes_reused": False,
                "source_outcomes_exposed_to_target_builder": False,
                "target_outcomes_read_pre_freeze": False,
            },
            "claim_boundary": EXPECTED_CLAIM_BOUNDARY,
        }
    finally:
        _close_snapshot(snapshot)


def build_record() -> dict[str, object]:
    record = _validate_and_build_record()
    if any(
        forbidden in _canonical_bytes(record)
        for forbidden in (
            b'"metrics"', b'"observations"', b'"detector_candidates"',
            b'"births"', b'"unique_ids"',
        )
    ):
        raise AdoptionError("sanitized adoption permit contains forbidden outcomes")
    return record


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise AdoptionError("zero-progress adoption write")
        offset += written


def write_once(output: Path, record: Mapping[str, object]) -> dict[str, object]:
    if output != DEFAULT_OUTPUT or output.expanduser().absolute() != output:
        raise AdoptionError("adoption output path is not the frozen canonical path")
    if output.parent.resolve(strict=True) != output.parent:
        raise AdoptionError("adoption parent is not canonical and symlink-free")
    payload = _canonical_bytes(record)
    parent_visible = os.lstat(output.parent)
    parent_fd = os.open(
        output.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        parent_held = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_held.st_mode)
            or stat.S_ISLNK(parent_visible.st_mode)
            or (int(parent_visible.st_dev), int(parent_visible.st_ino))
            != (int(parent_held.st_dev), int(parent_held.st_ino))
            or int(parent_held.st_uid) != int(os.getuid())
            or int(parent_held.st_dev) != EXPECTED_R3_DEVICE_ID
            or probe_audit._fstatfs_magic(parent_fd)
            != probe_audit.EXT4_SUPER_MAGIC
        ):
            raise AdoptionError("adoption parent identity/filesystem drift")
        try:
            os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AdoptionError("adoption namespace is already consumed")
        fd = os.open(
            output.name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o444,
            dir_fd=parent_fd,
        )
        try:
            os.fchmod(fd, 0o444)
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o444
                or int(opened.st_nlink) != 1
            ):
                raise AdoptionError("adoption reservation identity/mode failure")
            identity = (int(opened.st_dev), int(opened.st_ino))
            _write_all(fd, payload)
            os.fsync(fd)
            final = os.fstat(fd)
            visible = os.stat(
                output.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                (int(final.st_dev), int(final.st_ino)) != identity
                or (int(visible.st_dev), int(visible.st_ino)) != identity
                or stat.S_ISLNK(visible.st_mode)
                or stat.S_IMODE(final.st_mode) != 0o444
                or int(final.st_size) != len(payload)
            ):
                raise AdoptionError("adoption publication identity drift")
            os.fsync(parent_fd)
            held_payload, held_stat = _read_fd(
                fd, identity, label="published adoption permit"
            )
            visible_after = os.stat(
                output.name, dir_fd=parent_fd, follow_symlinks=False
            )
            parent_after = os.lstat(output.parent)
            if (
                held_payload != payload
                or stat.S_IMODE(held_stat.st_mode) != 0o444
                or stat.S_ISLNK(visible_after.st_mode)
                or (int(visible_after.st_dev), int(visible_after.st_ino))
                != identity
                or stat.S_ISLNK(parent_after.st_mode)
                or (int(parent_after.st_dev), int(parent_after.st_ino))
                != (int(parent_held.st_dev), int(parent_held.st_ino))
            ):
                raise AdoptionError("adoption held/visible bytes or identity mismatch")
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)
    return _identity(output, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--action", choices=("check", "write-once"), required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = build_record()
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_R3_ADOPTION_PREPUBLICATION_CHECK",
            "record_sha256": hashlib.sha256(_canonical_bytes(record)).hexdigest(),
            "record_size_bytes": len(_canonical_bytes(record)),
            "producer_started": False,
            "target_outcomes_read": False,
        }
        if args.action == "write-once":
            result["adoption"] = write_once(args.output, record)
            result["status"] = "PASS_R3_ADOPTION_SEALED"
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AdoptionError, probe_audit.AuditFailure, OSError, ValueError, KeyError) as exc:
        print(f"ADOPTION_BLOCKED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
