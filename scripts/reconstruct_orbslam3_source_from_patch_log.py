#!/usr/bin/env python3
"""Reconstruct an earlier ORB-SLAM3 source tree by reversing recorded patches."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecordedChange:
    timestamp: str
    session_index: int
    line_number: int
    change_index: int
    relative_path: str
    change_type: str
    unified_diff: str | None
    added_content: str | None
    call_id: str
    session_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-source", required=True)
    parser.add_argument("--output-source", required=True)
    parser.add_argument("--recorded-source-prefix", required=True)
    parser.add_argument("--session-jsonl", action="append", required=True)
    parser.add_argument("--since", required=True, help="Inclusive ISO-8601 UTC timestamp.")
    parser.add_argument("--through", required=True, help="Inclusive ISO-8601 UTC timestamp.")
    parser.add_argument("--expected-change-count", type=int)
    parser.add_argument("--baseline-hashes", required=True)
    parser.add_argument("--expected-source-hash-count", type=int, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_changes(
    sessions: list[Path], prefix: str, since: str, through: str
) -> list[RecordedChange]:
    normalized_prefix = prefix.rstrip("/") + "/"
    changes: list[RecordedChange] = []
    for session_index, session in enumerate(sessions):
        with session.open(encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = str(record.get("timestamp", ""))
                if not (since <= timestamp <= through):
                    continue
                payload = record.get("payload", {})
                if record.get("type") != "event_msg" or payload.get("type") != "patch_apply_end":
                    continue
                if payload.get("success") is not True:
                    continue
                raw_changes = payload.get("changes")
                if not isinstance(raw_changes, dict):
                    continue
                for change_index, (raw_path, raw_change) in enumerate(raw_changes.items()):
                    if not raw_path.startswith(normalized_prefix) or not isinstance(raw_change, dict):
                        continue
                    relative_path = raw_path[len(normalized_prefix) :]
                    if not relative_path or relative_path.startswith("../"):
                        raise SystemExit(f"unsafe recorded path: {raw_path}")
                    changes.append(
                        RecordedChange(
                            timestamp=timestamp,
                            session_index=session_index,
                            line_number=line_number,
                            change_index=change_index,
                            relative_path=relative_path,
                            change_type=str(raw_change.get("type", "")),
                            unified_diff=raw_change.get("unified_diff"),
                            added_content=raw_change.get("content"),
                            call_id=str(payload.get("call_id", "")),
                            session_path=str(session.resolve()),
                        )
                    )
    changes.sort(
        key=lambda item: (
            item.timestamp,
            item.session_index,
            item.line_number,
            item.change_index,
        )
    )
    identities = {
        (item.timestamp, item.call_id, item.relative_path) for item in changes
    }
    if len(identities) != len(changes):
        raise SystemExit("duplicate recorded patch identities across selected sessions")
    if not changes:
        raise SystemExit("no matching patch changes found")
    return changes


def copy_source_tree(current: Path, output: Path) -> None:
    if output.exists():
        raise SystemExit(f"refusing existing output source: {output}")
    current = current.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory).resolve()
        relative = directory_path.relative_to(current)
        ignored: set[str] = set()
        if relative == Path("."):
            ignored.update(name for name in names if name in {"build", "lib"})
        if relative == Path("Examples_old/Monocular"):
            ignored.update(
                name
                for name in names
                if (directory_path / name).is_file()
                and (directory_path / name).suffix == ""
            )
        return ignored

    shutil.copytree(current, output, symlinks=True, ignore=ignore)


def reverse_update(output: Path, change: RecordedChange) -> None:
    if not change.unified_diff:
        raise SystemExit(f"missing unified diff for update: {change.relative_path}")
    patch_text = (
        f"--- a/{change.relative_path}\n"
        f"+++ b/{change.relative_path}\n"
        f"{change.unified_diff.rstrip()}\n"
    )
    result = subprocess.run(
        ["patch", "--batch", "--silent", "--fuzz=0", "-R", "-p1", "-d", str(output)],
        input=patch_text,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"failed to reverse {change.relative_path} from {change.session_path}:"
            f"{change.line_number}\nstdout={result.stdout}\nstderr={result.stderr}"
        )


def reverse_add(output: Path, change: RecordedChange) -> None:
    path = output / change.relative_path
    if change.added_content is None:
        raise SystemExit(f"missing recorded content for added file: {change.relative_path}")
    if not path.is_file():
        raise SystemExit(f"recorded added file is absent before reversal: {path}")
    current = path.read_text(encoding="utf-8")
    if current != change.added_content:
        raise SystemExit(f"added file no longer matches recorded initial content: {path}")
    path.unlink()


def reverse_changes(output: Path, changes: list[RecordedChange]) -> None:
    for change in reversed(changes):
        if change.change_type == "update":
            reverse_update(output, change)
        elif change.change_type == "add":
            reverse_add(output, change)
        else:
            raise SystemExit(
                f"unsupported recorded change type {change.change_type!r}: {change.relative_path}"
            )


def validate_reconstruction(output: Path) -> dict[str, str]:
    forbidden = (
        "ExternalSeedAudit",
        "ORB_SLAM3_ENABLE_SEED_AUDIT",
        "ORB_SLAM3_SEED_AUDIT_DIR",
        "auditToken",
        "ExternalKeypointSeed",
    )
    roots = [output / "CMakeLists.txt", output / "include", output / "src", output / "Examples_old"]
    violations: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix not in {"", ".h", ".cc", ".cpp", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = [token for token in forbidden if token in text]
            if hits:
                violations.append(f"{path.relative_to(output)}:{','.join(hits)}")
    if violations:
        raise SystemExit(f"instrumentation references remain after reconstruction: {violations[:10]}")
    key_files = (
        "CMakeLists.txt",
        "include/ORBextractor.h",
        "include/System.h",
        "include/Tracking.h",
        "src/ORBextractor.cc",
        "src/System.cc",
        "src/Tracking.cc",
        "src/LocalMapping.cc",
        "src/MapPoint.cc",
        "Examples_old/Monocular/mono_euroc.cc",
    )
    return {relative: sha256(output / relative) for relative in key_files}


def validate_baseline_hashes(
    output: Path, baseline_path: Path, recorded_prefix: str, expected_count: int
) -> dict[str, str]:
    prefix = recorded_prefix.rstrip("/") + "/"
    matched: dict[str, str] = {}
    for line in baseline_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise SystemExit(f"malformed baseline hash line: {line!r}")
        expected, raw_path = fields
        if not raw_path.startswith(prefix):
            continue
        relative = raw_path[len(prefix) :]
        candidate = output / relative
        if not candidate.is_file():
            continue
        actual = sha256(candidate)
        if actual != expected:
            raise SystemExit(
                f"reconstructed source hash mismatch for {relative}: {actual} != {expected}"
            )
        matched[relative] = actual
    if len(matched) != expected_count:
        raise SystemExit(
            f"expected {expected_count} reconstructed source hash anchors, matched {len(matched)}"
        )
    return matched


def main() -> int:
    args = parse_args()
    current = Path(args.current_source).resolve()
    output = Path(args.output_source).resolve()
    sessions = [Path(value).resolve() for value in args.session_jsonl]
    baseline_hashes = Path(args.baseline_hashes).resolve()
    if (
        not current.is_dir()
        or any(not path.is_file() for path in sessions)
        or not baseline_hashes.is_file()
    ):
        raise SystemExit("missing current source, session JSONL, or baseline hashes")
    changes = collect_changes(
        sessions,
        args.recorded_source_prefix,
        args.since,
        args.through,
    )
    if args.expected_change_count is not None and len(changes) != args.expected_change_count:
        raise SystemExit(
            f"expected {args.expected_change_count} changes, selected {len(changes)}"
        )
    copy_source_tree(current, output)
    reverse_changes(output, changes)
    source_hashes = validate_reconstruction(output)
    baseline_matches = validate_baseline_hashes(
        output,
        baseline_hashes,
        args.recorded_source_prefix,
        args.expected_source_hash_count,
    )
    manifest = {
        "schema_version": 1,
        "current_source": str(current),
        "output_source": str(output),
        "recorded_source_prefix": args.recorded_source_prefix,
        "sessions": [str(path) for path in sessions],
        "session_sha256": {str(path): sha256(path) for path in sessions},
        "since": args.since,
        "through": args.through,
        "reversed_change_count": len(changes),
        "reversed_changes": [
            {
                "timestamp": item.timestamp,
                "session": item.session_path,
                "line": item.line_number,
                "call_id": item.call_id,
                "path": item.relative_path,
                "type": item.change_type,
            }
            for item in changes
        ],
        "reconstructed_source_sha256": source_hashes,
        "baseline_hash_file": str(baseline_hashes),
        "baseline_hash_file_sha256": sha256(baseline_hashes),
        "baseline_source_hash_matches": baseline_matches,
        "validation": "no instrumentation references in selected source roots",
    }
    (output / "preaudit_reconstruction_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"reconstructed {output} by reversing {len(changes)} recorded changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
