#!/usr/bin/env python3
"""Prove that the frozen B1 KLT payload path survived four exporter patches."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
SESSION = Path(
    "/home/ma/.codex/sessions/2026/08/08/"
    "rollout-2026-08-08T15-46-02-019fe056-07d7-79b3-bcbb-cc543d382467.jsonl"
)
DEFAULT_OUTPUT = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "b1_klt_exporter_7ed_to_567_transition_proof_v2.json"
)
EXPORTER_SESSION_PATH = "/home/ma/AQUA-FE_WS/uw_frontend/ros/export_vins_features.py"
SESSION_SHA256 = "2ea5f5ceb61477f2fa0557b85c3955fce872b070f31a5c281a521b3504afcedc"
OLD_SHA256 = "7ed31890e3a55a528430e912df885830176b3c3432c420860a39d714bceae7cf"
OLD_SIZE = 435_551
CURRENT_SHA256 = "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"
CURRENT_SIZE = 437_542
PATCHES = (
    {
        "jsonl_line": 4556,
        "timestamp": "2026-08-09T17:22:27.719Z",
        "diff_sha256": "c9267362c615ddbf370ccdebd0fa39ab77efa02d7e2a8e043c6ad82b45bc7f18",
        "diff_size_bytes": 2025,
        "hunks": ["-2406,3 +2406,9", "-2416,3 +2422,2", "-4534,3 +4539,9", "-4551,5 +4562,13", "-4743,5 +4762,10"],
        "scope": "pairwise learned-method camera/normalizer wiring; KLT branch unchanged",
    },
    {
        "jsonl_line": 4561,
        "timestamp": "2026-08-09T17:22:33.703Z",
        "diff_sha256": "068bb64e614cf13bdabd4087f5dbaca2116f82a3fafbe136f79dc9b424d120fe",
        "diff_size_bytes": 296,
        "hunks": ["-10291,2 +10291,9"],
        "scope": "pairwise camera focal-mean helper",
    },
    {
        "jsonl_line": 4566,
        "timestamp": "2026-08-09T17:22:44.550Z",
        "diff_sha256": "a2786bef7590bc9df62d17247016a17dfa9fbf7fe5dd17da4c3483f8e8731391",
        "diff_size_bytes": 1756,
        "hunks": ["-2507,2 +2507,7", "-3808,2 +3813,27"],
        "scope": "pairwise geometry metrics columns only",
    },
    {
        "jsonl_line": 4591,
        "timestamp": "2026-08-09T17:25:34.108Z",
        "diff_sha256": "c3d0da7b00629639b9a80c417cfa1204e5ac881df39562f1a572a6f0bd4f7cae",
        "diff_size_bytes": 2425,
        "hunks": ["-3813,27 +3813,3", "-10328,2 +10304,32"],
        "scope": "metrics-only helper refactor",
    },
)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class ProofError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_hunks(diff: str) -> list[tuple[int, int, int, int, list[str]]]:
    lines = diff.splitlines(keepends=True)
    result: list[tuple[int, int, int, int, list[str]]] = []
    index = 0
    while index < len(lines):
        match = HUNK_RE.match(lines[index].rstrip("\n"))
        if match is None:
            raise ProofError("PATCH_HUNK_HEADER_INVALID")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("@@ "):
            if not lines[index] or lines[index][0] not in " +-":
                raise ProofError("PATCH_BODY_INVALID")
            body.append(lines[index])
            index += 1
        result.append((old_start, old_count, new_start, new_count, body))
    return result


def reverse_apply(text: str, diff: str) -> str:
    """Reverse one headerless unified diff with exact context checks."""

    current = text.splitlines(keepends=True)
    output: list[str] = []
    cursor = 0
    for _old_start, old_count, new_start, new_count, body in _parse_hunks(diff):
        target = new_start - 1
        if target < cursor or target > len(current):
            raise ProofError("PATCH_TARGET_RANGE_INVALID")
        output.extend(current[cursor:target])
        consumed = 0
        produced = 0
        cursor = target
        for row in body:
            prefix, content = row[0], row[1:]
            if prefix in " +":
                if cursor >= len(current) or current[cursor] != content:
                    raise ProofError("PATCH_CONTEXT_MISMATCH")
                cursor += 1
                consumed += 1
            if prefix in " -":
                output.append(content)
                produced += 1
        if consumed != new_count or produced != old_count:
            raise ProofError("PATCH_COUNT_MISMATCH")
    output.extend(current[cursor:])
    return "".join(output)


def _hunk_labels(diff: str) -> list[str]:
    labels: list[str] = []
    for line in diff.splitlines():
        match = HUNK_RE.match(line)
        if match:
            old_count = match.group(2) or "1"
            new_count = match.group(4) or "1"
            labels.append(
                f"-{match.group(1)},{old_count} +{match.group(3)},{new_count}"
            )
    return labels


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ProofError(f"FUNCTION_MISSING:{name}")


def _klt_branch(tree: ast.Module) -> ast.If:
    function = _function(tree, "_build_tracker")
    for node in function.body:
        test = node.test if isinstance(node, ast.If) else None
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "method"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "klt"
        ):
            return node
    raise ProofError("KLT_FACTORY_BRANCH_MISSING")


def _ast_hash(node: ast.AST) -> str:
    return sha256_bytes(ast.dump(node, include_attributes=False).encode("utf-8"))


def _read_patch_events(session: Path) -> tuple[list[dict[str, object]], list[str]]:
    expected_by_line = {int(row["jsonl_line"]): row for row in PATCHES}
    observed: list[dict[str, object]] = []
    diffs: list[str] = []
    with session.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line_number not in expected_by_line:
                continue
            record = json.loads(line)
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "patch_apply_end":
                raise ProofError(f"PATCH_EVENT_TYPE_MISMATCH:{line_number}")
            if payload.get("success") is not True:
                raise ProofError(f"PATCH_EVENT_NOT_SUCCESS:{line_number}")
            changes = payload.get("changes")
            if not isinstance(changes, dict) or set(changes) != {EXPORTER_SESSION_PATH}:
                raise ProofError(f"PATCH_TARGET_SET_MISMATCH:{line_number}")
            change = changes[EXPORTER_SESSION_PATH]
            if not isinstance(change, dict) or change.get("type") != "update":
                raise ProofError(f"PATCH_CHANGE_TYPE_MISMATCH:{line_number}")
            diff = change.get("unified_diff")
            if not isinstance(diff, str):
                raise ProofError(f"PATCH_DIFF_MISSING:{line_number}")
            expected = expected_by_line[line_number]
            actual = {
                "jsonl_line": line_number,
                "timestamp": record.get("timestamp"),
                "diff_sha256": sha256_bytes(diff.encode("utf-8")),
                "diff_size_bytes": len(diff.encode("utf-8")),
                "hunks": _hunk_labels(diff),
                "scope": expected["scope"],
            }
            if actual != expected:
                raise ProofError(f"PATCH_IDENTITY_MISMATCH:{line_number}")
            observed.append(actual)
            diffs.append(diff)
    if len(observed) != len(PATCHES):
        raise ProofError("PATCH_EVENT_COUNT_MISMATCH")
    return observed, diffs


def build_proof(
    *, exporter: Path = EXPORTER, session: Path = SESSION
) -> dict[str, object]:
    current_bytes = exporter.read_bytes()
    if len(current_bytes) != CURRENT_SIZE or sha256_bytes(current_bytes) != CURRENT_SHA256:
        raise ProofError("CURRENT_EXPORTER_IDENTITY_MISMATCH")
    if session.stat().st_size <= 0 or sha256_file(session) != SESSION_SHA256:
        raise ProofError("SESSION_IDENTITY_MISMATCH")
    events, diffs = _read_patch_events(session)
    reconstructed = current_bytes.decode("utf-8")
    for diff in reversed(diffs):
        reconstructed = reverse_apply(reconstructed, diff)
    old_bytes = reconstructed.encode("utf-8")
    if len(old_bytes) != OLD_SIZE or sha256_bytes(old_bytes) != OLD_SHA256:
        raise ProofError("RECONSTRUCTED_OLD_IDENTITY_MISMATCH")

    old_tree = ast.parse(reconstructed)
    current_tree = ast.parse(current_bytes.decode("utf-8"))
    old_klt_hash = _ast_hash(_klt_branch(old_tree))
    current_klt_hash = _ast_hash(_klt_branch(current_tree))
    old_cloud_hash = _ast_hash(_function(old_tree, "_tracks_to_vins_pointcloud"))
    current_cloud_hash = _ast_hash(
        _function(current_tree, "_tracks_to_vins_pointcloud")
    )
    if old_klt_hash != current_klt_hash:
        raise ProofError("KLT_FACTORY_AST_CHANGED")
    if old_cloud_hash != current_cloud_hash:
        raise ProofError("POINTCLOUD_PAYLOAD_AST_CHANGED")

    return {
        "schema_version": "aqua-fe-b1-klt-exporter-transition-proof-v2",
        "status": "PASS",
        "contract_pass": True,
        "source_session": {
            "path": str(session),
            "sha256": SESSION_SHA256,
            "privacy_boundary": "only four patch_apply_end records were extracted",
        },
        "patches_forward_order": events,
        "reverse_order_jsonl_lines": [4591, 4566, 4561, 4556],
        "reconstruction": {
            "current": {
                "path": str(exporter.resolve()),
                "size_bytes": CURRENT_SIZE,
                "sha256": CURRENT_SHA256,
            },
            "reconstructed_old": {
                "size_bytes": OLD_SIZE,
                "sha256": OLD_SHA256,
            },
        },
        "branch_isolation": {
            "klt_factory_branch_ast_sha256": old_klt_hash,
            "klt_factory_old_equals_current": True,
            "vins_pointcloud_payload_function_ast_sha256": old_cloud_hash,
            "vins_pointcloud_payload_old_equals_current": True,
            "changed_scope": [
                "DL-VINS learned pairwise camera normalization wiring",
                "DL-VINS learned pairwise geometry metrics",
            ],
            "scientific_boundary": (
                "This proves source-path compatibility for B1 KLT export only; "
                "it is not a trajectory result or a learned-method claim."
            ),
        },
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def render(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    payload = build_proof()
    if args.check_only:
        expected = render(payload)
        if not args.output.is_file() or args.output.read_bytes() != expected:
            raise ProofError("FROZEN_PROOF_BYTES_MISMATCH")
    else:
        write_exclusive(args.output, render(payload))
    print(f"B1_EXPORTER_TRANSITION_PROOF_PASS output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
