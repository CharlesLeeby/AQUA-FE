#!/usr/bin/env python3
"""Build the frozen execution lock for the independent A09 AQUA-FE v2 run.

This builder is intentionally separate from the runner.  It is safe to import
and its ``static-selftest`` command does not inspect A09 KLT artifacts.  The
``print-candidate`` and ``write-lock`` commands are only lawful after the KLT
stage has been accepted; both perform the complete KLT dependency audit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNNER_PATH = ROOT / "scripts/run_a09_samehistory_warmstart_v2_aquafe.py"
BUILDER_PATH = Path(__file__).absolute()
PROTOCOL_PATH = ROOT / "papers/a09_samehistory_warmstart_v2_aquafe_protocol.md"


def source_identity(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"SOURCE_NOT_REGULAR:{path}")
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise RuntimeError(f"SOURCE_CHANGED_WHILE_LOADING:{path}")
        return {
            "path": str(path), "size_bytes": int(before.st_size),
            "sha256": digest.hexdigest(), "device": int(before.st_dev),
            "inode": int(before.st_ino), "mtime_ns": int(before.st_mtime_ns),
            "ctime_ns": int(before.st_ctime_ns),
        }
    finally:
        os.close(descriptor)


def load_runner() -> Any:
    before = source_identity(RUNNER_PATH)
    name = "_a09_aquafe_v2_runner_for_lock_builder"
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("RUNNER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    after = source_identity(RUNNER_PATH)
    if before != after:
        raise RuntimeError("RUNNER_CHANGED_DURING_IMPORT")
    module._lock_builder_loaded_source_identity = before
    return module


def public_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot[key]
        for key in ("path", "size_bytes", "sha256")
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def require_unstarted(runner: Any) -> None:
    runner.require(
        not runner.AQUA_DIR.exists() and not runner.AQUA_DIR.is_symlink(),
        "AQUA_CANONICAL_ALREADY_EXISTS",
    )
    runner.require(
        not runner.AQUA_STAGE.exists() and not runner.AQUA_STAGE.is_symlink(),
        "AQUA_STAGE_ALREADY_EXISTS",
    )
    runner.require(
        not runner.AQUA_FAILURE.exists() and not runner.AQUA_FAILURE.is_symlink(),
        "AQUA_FAILURE_ALREADY_EXISTS",
    )


def require_frozen_protocol(runner: Any) -> None:
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    runner.require(
        "Status: **FROZEN FOR AQUA-FE V2 EXECUTION.**" in text,
        "PROTOCOL_NOT_FROZEN_FOR_EXECUTION",
    )
    runner.require(
        "DRAFT" not in text and "DO NOT RUN" not in text,
        "PROTOCOL_STILL_DRAFT",
    )


def build_candidate(runner: Any) -> dict[str, Any]:
    """Audit all authorities and return, but do not write, the exact lock."""
    require_unstarted(runner)
    require_frozen_protocol(runner)
    authority = runner.static_authority_snapshots()
    config = authority["config_chain"]
    runner.require(
        config["merged_config_sha256"] == runner.MERGED_CONFIG_SHA256,
        "BUILDER_MERGED_CONFIG",
    )

    identities: dict[str, dict[str, Any]] = {}
    for key, (path, size, digest) in runner.STATIC_EXPECTED.items():
        snapshot = authority[key]
        runner.require(
            snapshot["size_bytes"] == size and snapshot["sha256"] == digest,
            f"BUILDER_STATIC_IDENTITY:{key}",
        )
        identities[key] = {
            "path": str(path), "size_bytes": size, "sha256": digest,
        }

    for key, path in {
        "runner": RUNNER_PATH,
        "builder": BUILDER_PATH,
        "protocol": PROTOCOL_PATH,
    }.items():
        identities[key] = public_identity(runner.snapshot_file(path))
    runner.require(
        identities["runner"]
        == public_identity(runner._lock_builder_loaded_source_identity),
        "BUILDER_LOADED_RUNNER_IDENTITY",
    )

    for key, path in runner.KLT_LOCK_FILES.items():
        identities[key] = public_identity(runner.snapshot_file(path))
    identities[runner.KLT_STRENGTH_IDENTITY_KEY] = public_identity(
        runner.snapshot_file(runner.KLT_STRENGTH_ADDENDUM)
    )
    identities[runner.KLT_STRENGTH_BUILDER_IDENTITY_KEY] = public_identity(
        runner.snapshot_file(runner.KLT_STRENGTH_BUILDER)
    )

    klt_receipt = runner.verify_klt_receipt()
    klt_strength = runner.verify_klt_strength_addendum()
    klt_audit = runner.audit_raw_and_klt()
    runner.require(
        klt_audit.get("status") == "PASS_KLT_DEPENDENCY_ARTIFACT_AUDIT",
        "BUILDER_KLT_AUDIT",
    )

    argv = runner.build_argv()
    environment = runner.effective_environment()
    lock = {
        "schema_version": runner.LOCK_SCHEMA,
        "status": "FROZEN_BEFORE_AQUAFE_POPEN",
        "created_at_utc": utc_now(),
        "stage": "aquafe",
        "argv": argv,
        "argv_sha256": runner.compact_sha(argv),
        "effective_environment": environment,
        "effective_environment_sha256": runner.compact_sha(environment),
        "identities": identities,
        "config_chain": {
            "ordered_paths": [str(path) for path, _ in runner.CONFIG_CHAIN],
            "merged_config_sha256": runner.MERGED_CONFIG_SHA256,
            "effective_xfeat": runner.EFFECTIVE_XFEAT,
            "effective_xfeat_sha256": runner.EFFECTIVE_XFEAT_SHA256,
            "external_tools_link": {
                "path": str(runner.EXTERNAL_TOOLS_LINK),
                "target": runner.EXTERNAL_TOOLS_TARGET,
            },
        },
        "dependency_acceptance": {
            "klt_receipt": klt_receipt,
            "klt_execution_strength_addendum": klt_strength,
            "klt_artifact_audit": klt_audit,
        },
        "execution_policy": runner.LOCK_EXECUTION_POLICY,
        "claim_boundary": runner.LOCK_CLAIM_BOUNDARY,
    }
    # Exercise the exact runner verifier logic without publishing a lock by
    # comparing every field that does not require a pathname-backed lock file.
    runner.require(set(identities) == (
        set(runner.STATIC_EXPECTED) | set(runner.KLT_LOCK_FILES)
        | {
            "runner", "builder", "protocol", runner.KLT_STRENGTH_IDENTITY_KEY,
            runner.KLT_STRENGTH_BUILDER_IDENTITY_KEY,
        }
    ), "BUILDER_IDENTITY_SET")
    verify_candidate_authority(runner, lock)
    return lock


def verify_candidate_authority(runner: Any, lock: dict[str, Any]) -> None:
    identities = lock["identities"]
    for key, claim in identities.items():
        actual = public_identity(runner.snapshot_file(Path(claim["path"])))
        runner.require(actual == claim, f"BUILDER_CANDIDATE_IDENTITY_DRIFT:{key}")
    runner.require(
        identities["runner"]
        == public_identity(runner._lock_builder_loaded_source_identity),
        "BUILDER_LOADED_RUNNER_CHANGED",
    )
    config = runner.verify_config_chain()
    runner.require(
        lock["config_chain"]["merged_config_sha256"]
        == config["merged_config_sha256"]
        and lock["config_chain"]["effective_xfeat"] == config["effective_xfeat"]
        and lock["config_chain"]["effective_xfeat_sha256"]
        == config["effective_xfeat_sha256"],
        "BUILDER_CANDIDATE_CONFIG_DRIFT",
    )
    link = runner.verify_external_tools_link()
    runner.require(
        lock["config_chain"]["external_tools_link"]
        == {"path": link["path"], "target": link["target"]},
        "BUILDER_CANDIDATE_EXTERNAL_TOOLS_LINK_DRIFT",
    )


def publish_lock(runner: Any, lock: dict[str, Any], output: Path) -> dict[str, Any]:
    output = output.absolute()
    runner.require(output == runner.DEFAULT_LOCK, f"NONCANONICAL_LOCK_PATH:{output}")
    runner.no_symlink_components(output, missing_leaf_ok=True)
    runner.require(not output.exists() and not output.is_symlink(), "LOCK_ALREADY_EXISTS")
    verify_candidate_authority(runner, lock)
    helper = runner.a10_helper()
    status = helper.atomic_publish(output, lock, propagate_interruption_after_commit=True)
    runner.require(
        status in {"PUBLISHED", "PUBLISHED_POSTLINK_RECOVERED"},
        f"LOCK_PUBLICATION:{status}",
    )
    snapshot = runner.snapshot_file(output)
    parsed, verified_snapshot = runner.verify_lock(output)
    runner.require(parsed == lock and snapshot == verified_snapshot, "LOCK_POSTPUBLICATION_VERIFY")
    verify_candidate_authority(runner, lock)
    return {
        "status": "LOCK_PUBLISHED_AND_VERIFIED",
        "lock": public_identity(snapshot),
        "argv_sha256": lock["argv_sha256"],
        "effective_environment_sha256": lock["effective_environment_sha256"],
    }


def static_selftest(runner: Any) -> dict[str, Any]:
    """Pure test: deliberately does not inspect the A09 KLT directory."""
    for path in (RUNNER_PATH, BUILDER_PATH, PROTOCOL_PATH):
        info = path.lstat()
        runner.require(stat.S_ISREG(info.st_mode), f"STATIC_FILE_NOT_REGULAR:{path}")
        runner.require(not path.is_symlink(), f"STATIC_FILE_IS_SYMLINK:{path}")
    runner.require(BUILDER_PATH == runner.BUILDER, "BUILDER_PATH_DISAGREEMENT")
    runner.require(PROTOCOL_PATH == runner.PROTOCOL, "PROTOCOL_PATH_DISAGREEMENT")
    runner.require(RUNNER_PATH == Path(runner.__file__).absolute(), "RUNNER_PATH_DISAGREEMENT")
    return {
        "status": "PASS_BUILDER_STATIC_SELFTEST_NO_A09_KLT_READ",
        "runner": public_identity(runner.snapshot_file(RUNNER_PATH)),
        "builder": public_identity(runner.snapshot_file(BUILDER_PATH)),
        "protocol": public_identity(runner.snapshot_file(PROTOCOL_PATH)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("static-selftest", "print-candidate", "write-lock"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    runner = load_runner()
    try:
        if args.command == "static-selftest":
            runner.require(args.output is None, "STATIC_SELFTEST_REJECTS_OUTPUT")
            result = static_selftest(runner)
        else:
            with runner.global_mutex():
                lock = build_candidate(runner)
                if args.command == "print-candidate":
                    runner.require(args.output is None, "PRINT_CANDIDATE_REJECTS_OUTPUT")
                    result = lock
                else:
                    runner.require(args.output is not None, "WRITE_LOCK_REQUIRES_EXPLICIT_OUTPUT")
                    result = publish_lock(runner, lock, args.output)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (runner.AquaV2Error, OSError, ValueError) as error:
        print(f"AQUAFE_LOCK_BUILDER_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
