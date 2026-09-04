#!/usr/bin/env python3
"""Materialize the isolated A08 recovered-July frontend execution tree."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import Any, Iterable


ROOT = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/backups/"
    "frozen_frontend_source_20260716_before_adaptive_dev.tar.gz"
)
RAW_BAG = EXPERIMENT / "raw/archaeo08_0000_4660.bag"
RAW_RECEIPT = EXPERIMENT / "raw/raw_materialization_receipt_v1.json"
PROTOCOL = ROOT / "papers/a08_hfnet_history_matched_support_extension_v1_protocol.md"
SOURCE_PACKAGE = ROOT / "uw_frontend"

ARCHIVE_EXPECTED = (
    89_815,
    "7e13b845a2d7b88dc3b20c9ad2df89c2506e80ebaf89bb25772bdd13ae4af21c",
)
FIXED_INPUTS = {
    RAW_BAG: (
        1_242_450_892,
        "9f7d21f7fe45f12f72c7e922be39e9b48601006f14254a5355992aab17ee16c2",
    ),
    RAW_RECEIPT: (
        7_604,
        "0e996bf0d81b7f13459085140e0fc87403d520fda46912f9dc6988ef73fa2fa3",
    ),
    PROTOCOL: (
        7_665,
        "2d202a342397e64b47a32a29834a59d76afaaae32002da7016373befc2fee466",
    ),
}

ARCHIVE_MEMBERS = {
    "scripts/run_xfeat_seedchain_arbitrated_eval.sh": (
        91_687,
        "82bd47f019a423fc3e8f92bf533c06556dd1eb9b2d20c49ba8ff09e435744fb0",
    ),
    "scripts/run_learned_seedchain_eval.sh": (
        4_061,
        "8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106",
    ),
    "uw_frontend/ros/export_vins_features.py": (
        432_487,
        "de78c8258f32bcea4c04d4d4fffa9fa8ac82abffbf896a1c73ba28b694702f67",
    ),
    "uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml": (
        1_964,
        "4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce",
    ),
    "scripts/filter_feature_bag_by_channel.py": (
        15_000,
        "745d8c5c07cbc8fb65e307221f744e5c4b44b3f93618c4ca68754a7060430e0d",
    ),
    "scripts/evaluate_vins_sim_ape.py": (
        10_127,
        "ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33",
    ),
    "scripts/evaluate_vins_tum.py": (
        8_906,
        "b994676b9e845c68427d01c8d80b1a4492ed2dedd25a770918cff61b0fea4ff4",
    ),
}

ADDITIONAL_SCRIPTS = (
    ROOT / "scripts/learned_seedchain_env.sh",
    ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
    ROOT / "scripts/record_vins_env.sh",
    ROOT / "scripts/wait_for_ros_subscribers.py",
)
XFEAT_FILES = (
    ROOT / "external_tools/accelerated_features/modules/__init__.py",
    ROOT / "external_tools/accelerated_features/modules/xfeat.py",
    ROOT / "external_tools/accelerated_features/modules/model.py",
    ROOT / "external_tools/accelerated_features/modules/interpolator.py",
    ROOT / "external_tools/accelerated_features/weights/xfeat.pt",
)


class OverlayError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise OverlayError(code)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode), f"NOT_REGULAR:{path}")
            return stream.read()
    except OSError as error:
        raise OverlayError(f"READ_REGULAR:{path}:{error}") from error


def identity_from_bytes(path: Path, payload: bytes) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": len(payload), "sha256": sha256_bytes(payload)}


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    payload = read_regular(path)
    result = identity_from_bytes(path, payload)
    require((len(payload), result["sha256"]) == expected, f"IDENTITY_DRIFT:{path}")
    return result


def source_package_files() -> list[Path]:
    result: list[Path] = []
    for path in sorted(SOURCE_PACKAGE.rglob("*")):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file() and not path.is_symlink():
            result.append(path)
        elif path.is_symlink():
            raise OverlayError(f"SOURCE_PACKAGE_SYMLINK:{path}")
    require(bool(result), "SOURCE_PACKAGE_EMPTY")
    return result


def tree_root(entries: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["relative_path"])):
        digest.update(
            (
                f"{entry['relative_path']}\0{entry['size_bytes']}\0"
                f"{entry['sha256']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def archive_payloads() -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        require(set(members) == set(ARCHIVE_MEMBERS), "ARCHIVE_MEMBER_SET")
        for name, expected in ARCHIVE_MEMBERS.items():
            stream = archive.extractfile(members[name])
            require(stream is not None, f"ARCHIVE_MEMBER_UNREADABLE:{name}")
            payload = stream.read()
            require((len(payload), sha256_bytes(payload)) == expected, f"ARCHIVE_MEMBER_DRIFT:{name}")
            values[name] = payload
    return values


def relative_external(path: Path) -> Path:
    return path.relative_to(ROOT)


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def preflight() -> dict[str, Any]:
    require(not OVERLAY.exists() and not OVERLAY.is_symlink(), "OVERLAY_ALREADY_EXISTS")
    fixed = {str(path): require_identity(path, expected) for path, expected in FIXED_INPUTS.items()}
    archive = require_identity(ARCHIVE, ARCHIVE_EXPECTED)
    archived = archive_payloads()
    package_entries: list[dict[str, Any]] = []
    for path in source_package_files():
        payload = read_regular(path)
        relative = path.relative_to(ROOT)
        package_entries.append(
            {
                "relative_path": str(relative),
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
    extras: dict[str, Any] = {}
    for path in (*ADDITIONAL_SCRIPTS, *XFEAT_FILES):
        payload = read_regular(path)
        extras[str(path)] = identity_from_bytes(path, payload)
    return {
        "status": "READY_OVERLAY_MATERIALIZATION",
        "output": str(OVERLAY),
        "fixed_inputs": fixed,
        "archive": archive,
        "archive_member_count": len(archived),
        "current_package_file_count": len(package_entries),
        "current_package_tree_sha256": tree_root(package_entries),
        "additional_inputs": extras,
        "frontend_or_vins_executed": False,
    }


def materialize() -> dict[str, Any]:
    ready = preflight()
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(OVERLAY, 0o700)
    execution_entries: dict[str, dict[str, Any]] = {}
    try:
        for source in source_package_files():
            relative = source.relative_to(ROOT)
            payload = read_regular(source)
            target = OVERLAY / relative
            write_exclusive(target, payload)
            execution_entries[str(relative)] = {
                "relative_path": str(relative),
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "origin": "current_transitive_closure_snapshot",
            }

        for source in (*ADDITIONAL_SCRIPTS, *XFEAT_FILES):
            relative = relative_external(source)
            payload = read_regular(source)
            target = OVERLAY / relative
            if target.exists():
                target.unlink()
            write_exclusive(target, payload)
            execution_entries[str(relative)] = {
                "relative_path": str(relative),
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "origin": "newly_frozen_transitive_dependency",
            }

        for name, payload in archive_payloads().items():
            target = OVERLAY / name
            if target.exists():
                target.unlink()
            write_exclusive(target, payload)
            execution_entries[name] = {
                "relative_path": name,
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "origin": "recovered_exact_july_seven_file_core",
            }

        manifest = {
            "schema_version": "aqua-fe-a08-recovered-july-overlay-manifest-v1",
            "status": "PASS_EXECUTION_TREE_FROZEN_BEFORE_FRONTEND",
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file_count": len(execution_entries),
            "tree_sha256": tree_root(execution_entries.values()),
            "entries": [
                execution_entries[name] for name in sorted(execution_entries)
            ],
        }
        manifest_path = OVERLAY / "execution_tree_manifest_v1.json"
        write_exclusive(manifest_path, canonical_json(manifest))
        receipt = {
            "schema_version": "aqua-fe-a08-recovered-july-overlay-materialization-v1",
            "status": "PASS_OVERLAY_MATERIALIZED_NO_FRONTEND_EXECUTED",
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "preflight": ready,
            "manifest": identity_from_bytes(manifest_path, read_regular(manifest_path)),
            "execution_tree": {
                "file_count": manifest["file_count"],
                "tree_sha256": manifest["tree_sha256"],
                "historical_core_exact": True,
                "complete_july_environment_reproduction": False,
                "label": "recovered seven-file July core plus newly frozen transitive closure",
            },
            "claim_boundary": {
                "current_workspace_files_modified": False,
                "frontend_or_vins_executed": False,
                "ape_or_rpe_computed": False,
            },
        }
        receipt_path = OVERLAY / "overlay_materialization_receipt_v1.json"
        write_exclusive(receipt_path, canonical_json(receipt))
        (OVERLAY / "logs/aqualoc_archaeo_vins").mkdir(
            parents=True, mode=0o755
        )
        os.chmod(OVERLAY, 0o555)
        return {
            "status": receipt["status"],
            "output": str(OVERLAY),
            "file_count": manifest["file_count"],
            "tree_sha256": manifest["tree_sha256"],
            "manifest": identity_from_bytes(manifest_path, read_regular(manifest_path)),
            "receipt": identity_from_bytes(receipt_path, read_regular(receipt_path)),
        }
    except BaseException:
        # This directory was claimed exclusively by this invocation.  A
        # partial tree has no completion receipt and is intentionally retained
        # fail-closed for diagnosis rather than silently retried.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "materialize"))
    args = parser.parse_args()
    try:
        result = preflight() if args.command == "preflight" else materialize()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (OverlayError, OSError, ValueError, tarfile.TarError) as error:
        print(f"OVERLAY_ERROR:{type(error).__name__}:{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
