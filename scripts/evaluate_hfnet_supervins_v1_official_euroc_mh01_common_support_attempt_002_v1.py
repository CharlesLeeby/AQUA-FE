#!/usr/bin/env python3
"""Additive corrective controller for Stage6 common-support attempt_002.

Scientific parsing, support, alignment, metrics, tables, figures, and bundle
construction execute directly from the sealed attempt_001 runner.  This module
changes only the report lexer and the additive attempt_002 lifecycle.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import traceback
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


ROOT = Path("/home/ma/AQUA-FE_WS")
BASE_RUNNER = ROOT / "scripts/evaluate_hfnet_supervins_v1_official_euroc_mh01_common_support_v1.py"
ADDENDUM = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_corrective_addendum_v1.json"
FAILURE_ADOPTION = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_001_failure_adoption_v1.json"
LOCK = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_execution_lock_v1.json"
AUTHORITY = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_execution_authority_v1.json"
RUNNER = Path(__file__).resolve()
TESTS = ROOT / "scripts/tests/test_evaluate_hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_v1.py"
TEST_RECEIPT = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_attempt_002_test_receipt_v1.json"

OLD_LOCK = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_execution_lock_v1.json"
OLD_AUTHORITY = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_execution_authority_v1.json"
OLD_EVIDENCE_ROOT = ROOT / "experiments/published_hfnet_supervins_v1_official_euroc_mh01_common_support_descriptive_20260821_r1"
OLD_ATTEMPT = OLD_EVIDENCE_ROOT / "attempt_001"
OLD_START_CLAIM = OLD_ATTEMPT / "evaluation_start_claim.json"
OLD_PREFLIGHT = OLD_ATTEMPT / "preflight_result.json"
OLD_RUN_RESULT = OLD_ATTEMPT / "run_result.json"

EVIDENCE_ROOT = ROOT / "experiments/published_hfnet_supervins_v1_official_euroc_mh01_common_support_descriptive_20260821_r2"
ATTEMPT = EVIDENCE_ROOT / "attempt_002"
ANALYSIS = ATTEMPT / "analysis-output"
FIGURES = ANALYSIS / "figures"
START_CLAIM = ATTEMPT / "evaluation_start_claim.json"
PREFLIGHT_RESULT = ATTEMPT / "preflight_result.json"
RUN_RESULT = ATTEMPT / "run_result.json"

TOKEN = "HFNET_SUPERVINS_STAGE6_MH01_COMMON_SUPPORT_ATTEMPT_002_CORRECTIVE_START_ONCE"
TOKEN_SHA256 = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
CONTROLLER_COMMAND = [
    "/usr/bin/python3.8", "-B", str(RUNNER), "--action", "run",
    "--authorization-token", TOKEN,
]

ADDENDUM_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-attempt-002-corrective-addendum-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-attempt-002-execution-lock-v1"
AUTHORITY_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-attempt-002-root-authority-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-attempt-002-result-v1"

EXPECTED_OLD_FILE_SET = ["evaluation_start_claim.json", "preflight_result.json", "run_result.json"]
FORBIDDEN_SINGLE_TOKEN_FORMS: Mapping[str, Tuple[str, ...]] = {
    "difference": ("difference", "differences"),
    "delta": ("delta", "deltas"),
    "ratio": ("ratio", "ratios"),
    "better": ("better",),
    "outperform": ("outperform", "outperforms", "outperformed", "outperforming"),
    "winner": ("winner", "winners"),
    "best": ("best",),
    "superior": ("superior", "superiority"),
    "rank": ("rank", "ranks", "ranked", "ranking", "rankings"),
    "percent": ("percent", "percentage", "percentages"),
    "improvement": ("improvement", "improvements"),
}
FORBIDDEN_TOKEN_PHRASES: Mapping[str, Tuple[Tuple[str, ...], ...]] = {
    "p-value": (("p", "value"), ("p", "values")),
    "confidence interval": (("confidence", "interval"), ("confidence", "intervals")),
    "effect size": (("effect", "size"), ("effect", "sizes")),
}
AUTHORITY_IDENTITY_KEYS = {
    "lock", "protocol", "runner", "tests", "test_receipt",
    "failure_adoption", "attempt_001_run_result",
}


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("sealed_stage6_attempt_001_runner", str(BASE_RUNNER))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load sealed attempt_001 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()

COMMITTED_RETURN_CODE: Optional[int] = None
COMMITTED_STATUS: Optional[str] = None

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_LIBC = ctypes.CDLL(None, use_errno=True)
_RENAMEAT2 = getattr(_LIBC, "renameat2", None)
if _RENAMEAT2 is not None:
    _RENAMEAT2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    ]
    _RENAMEAT2.restype = ctypes.c_int


def report_tokens(text: str) -> List[str]:
    """Return maximal lowercase ASCII-alphanumeric tokens.

    Underscore, hyphen, whitespace, and punctuation are separators.  Thus
    ``metric_ratio`` exposes the token ``ratio``, while ``generation`` remains
    one different token and cannot produce a substring false positive.
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def validate_report_boundary(texts: Sequence[str]) -> Dict[str, Any]:
    joined = "\n".join(texts).lower()
    tokens = report_tokens(joined)
    token_set = set(tokens)
    found: List[str] = []
    for label, forms in FORBIDDEN_SINGLE_TOKEN_FORMS.items():
        if any(form in token_set for form in forms):
            found.append(label)
    for label, phrases in FORBIDDEN_TOKEN_PHRASES.items():
        if any(any(tuple(tokens[index:index + len(phrase)]) == phrase for index in range(len(tokens) - len(phrase) + 1)) for phrase in phrases):
            found.append(label)
    if "%" in joined:
        found.append("%")
    return {
        "ok": not found,
        "forbidden_tokens_found": found,
        "lexer": "maximal_ascii_alphanumeric_whole_tokens_and_explicit_phrases",
        "substring_matching_used": False,
    }


def configure_base() -> None:
    replacements = {
        "FREEZE": ADDENDUM, "LOCK": LOCK, "AUTHORITY": AUTHORITY,
        "RUNNER": RUNNER, "TESTS": TESTS, "TEST_RECEIPT": TEST_RECEIPT,
        "EVIDENCE_ROOT": EVIDENCE_ROOT, "ATTEMPT": ATTEMPT,
        "ANALYSIS": ANALYSIS, "FIGURES": FIGURES,
        "START_CLAIM": START_CLAIM, "PREFLIGHT_RESULT": PREFLIGHT_RESULT,
        "RUN_RESULT": RUN_RESULT, "TOKEN": TOKEN, "TOKEN_SHA256": TOKEN_SHA256,
        "CONTROLLER_COMMAND": CONTROLLER_COMMAND, "FREEZE_SCHEMA": ADDENDUM_SCHEMA,
        "LOCK_SCHEMA": LOCK_SCHEMA, "AUTHORITY_SCHEMA": AUTHORITY_SCHEMA,
        "RESULT_SCHEMA": RESULT_SCHEMA,
    }
    for name, value in replacements.items():
        setattr(BASE, name, value)
    BASE.validate_report_boundary = validate_report_boundary


configure_base()


def lexical_exists(path: Path) -> bool:
    return os.path.lexists(str(path))


def read_regular_json_nofollow(path: Path, include_inode: bool = False) -> Tuple[Any, Dict[str, Any]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("JSON control path is not a regular non-symlink file")
        parts: List[bytes] = []
        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            parts.append(block)
            digest.update(block)
            total += len(block)
        after = os.fstat(fd)
        path_info = os.lstat(str(path))
    finally:
        os.close(fd)
    if not stat.S_ISREG(path_info.st_mode) or not (
        before.st_dev == after.st_dev == path_info.st_dev
        and before.st_ino == after.st_ino == path_info.st_ino
        and before.st_size == after.st_size == path_info.st_size == total
    ):
        raise ValueError("JSON control path changed during nofollow read")
    identity = {
        "sha256": digest.hexdigest(), "size_bytes": total,
        "mode": format(stat.S_IMODE(after.st_mode), "04o"), "nlink": after.st_nlink,
    }
    if include_inode:
        identity.update({"device": int(after.st_dev), "inode": int(after.st_ino)})
    return json.loads(b"".join(parts).decode("utf-8")), identity


def terminal_document_audit(path: Path, document: Mapping[str, Any]) -> Dict[str, Any]:
    payload = BASE.canonical_json_bytes(document)
    expected = {
        "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
        "mode": "0444", "nlink": 1,
    }
    try:
        observed_document, observed_with_inode = read_regular_json_nofollow(path, include_inode=True)
        observed = {key: observed_with_inode[key] for key in ("sha256", "size_bytes", "mode", "nlink")}
        observed_inode = [observed_with_inode["device"], observed_with_inode["inode"]]
        ok = observed == expected and observed_document == document
        error = None
    except Exception as exc:
        observed_document = None
        observed = None
        observed_inode = None
        ok = False
        error = "{}: {}".format(type(exc).__name__, exc)
    return {
        "ok": ok, "expected": expected, "observed": observed,
        "observed_inode": observed_inode,
        "document_exact": observed_document == document if observed_document is not None else False,
        "error": error,
    }


def terminal_write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("terminal staging write made no progress")
        offset += written


def terminal_set_readonly(fd: int) -> None:
    os.fchmod(fd, 0o444)


def terminal_file_fsync(fd: int) -> None:
    os.fsync(fd)


def terminal_publish_noreplace(staging: Path, final: Path) -> None:
    """Atomically move one sealed inode into place without replacing a name."""
    if _RENAMEAT2 is None:
        raise RuntimeError("renameat2(RENAME_NOREPLACE) is unavailable")
    result = _RENAMEAT2(
        _AT_FDCWD, os.fsencode(staging),
        _AT_FDCWD, os.fsencode(final),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), str(final))
        raise OSError(error, os.strerror(error), str(final))


def terminal_post_publish_hook() -> None:
    """Test seam after a confirmed successful renameat2; production is a no-op."""
    return None


def terminal_parent_fsync_with_retries(parent: Path, maximum_attempts: int = 3) -> Dict[str, Any]:
    errors: List[str] = []
    for attempt in range(1, maximum_attempts + 1):
        try:
            BASE.fsync_directory(parent)
            return {"confirmed": True, "attempts": attempt, "maximum_attempts": maximum_attempts, "errors": errors}
        except BaseException as exc:
            errors.append("{}: {}".format(type(exc).__name__, exc))
    return {"confirmed": False, "attempts": maximum_attempts, "maximum_attempts": maximum_attempts, "errors": errors}


def terminal_staging_path(path: Path) -> Path:
    return path.with_name("." + path.name + ".atomic-staging")


def terminal_unlink_once(path: Path) -> None:
    os.unlink(str(path))


def terminal_cleanup_staging_with_retries(path: Path, maximum_attempts: int = 3) -> Dict[str, Any]:
    errors: List[str] = []
    if not lexical_exists(path):
        return {"confirmed_absent": True, "attempts": 0, "maximum_attempts": maximum_attempts, "errors": errors}
    for attempt in range(1, maximum_attempts + 1):
        try:
            terminal_unlink_once(path)
        except BaseException as exc:
            errors.append("{}: {}".format(type(exc).__name__, exc))
        if not lexical_exists(path):
            return {"confirmed_absent": True, "attempts": attempt, "maximum_attempts": maximum_attempts, "errors": errors}
    return {"confirmed_absent": False, "attempts": maximum_attempts, "maximum_attempts": maximum_attempts, "errors": errors}


def reclaim_uncommitted_terminal_paths(path: Path) -> Dict[str, Any]:
    """Remove only uncommitted terminal names inside the owned attempt namespace."""
    if path != RUN_RESULT or path.parent != ATTEMPT or not BASE.NAMESPACE_OWNED:
        return {"ok": False, "failures": ["ownership_or_path_boundary"], "entries": {}}
    entries: Dict[str, Any] = {}
    failures: List[str] = []
    for candidate in (path, terminal_staging_path(path)):
        label = candidate.name
        record: Dict[str, Any] = {"path": str(candidate), "present_before": lexical_exists(candidate)}
        if record["present_before"]:
            try:
                info = os.lstat(str(candidate))
                record.update({
                    "mode_before": format(stat.S_IMODE(info.st_mode), "04o"),
                    "device_before": int(info.st_dev), "inode_before": int(info.st_ino),
                    "regular_before": stat.S_ISREG(info.st_mode),
                    "symlink_before": stat.S_ISLNK(info.st_mode),
                })
                if stat.S_ISDIR(info.st_mode):
                    raise ValueError("refuse to unlink directory at terminal pathname")
                cleanup = terminal_cleanup_staging_with_retries(candidate)
                record["cleanup"] = cleanup
                if not cleanup["confirmed_absent"]:
                    failures.append(label + ":cleanup")
            except BaseException as exc:
                record["error"] = "{}: {}".format(type(exc).__name__, exc)
                failures.append(label + ":" + record["error"])
        record["absent_after"] = not lexical_exists(candidate)
        if not record["absent_after"]:
            failures.append(label + ":still_present")
        entries[label] = record
    durability = terminal_parent_fsync_with_retries(path.parent)
    return {
        "ok": not failures and all(record["absent_after"] for record in entries.values()),
        "failures": list(dict.fromkeys(failures)), "entries": entries,
        "parent_directory_fsync": durability,
    }


def terminal_owned_final_audit(
    path: Path,
    document: Mapping[str, Any],
    expected_inode: Tuple[int, int],
    maximum_attempts: int = 3,
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {"ok": False, "observed": None}
    for attempt in range(1, maximum_attempts + 1):
        try:
            content_audit = terminal_document_audit(path, document)
        except BaseException as exc:
            content_audit = {
                "ok": False, "observed": None, "observed_inode": None,
                "error": "{}: {}".format(type(exc).__name__, exc),
            }
        observed_inode_list = content_audit.get("observed_inode")
        observed_inode: Optional[Tuple[int, int]] = (
            tuple(int(value) for value in observed_inode_list)
            if isinstance(observed_inode_list, list) and len(observed_inode_list) == 2
            else None
        )
        owned = observed_inode == expected_inode
        ok = bool(content_audit.get("ok")) and owned
        attempts.append({
            "attempt": attempt, "content_ok": bool(content_audit.get("ok")),
            "owned_inode_match": owned, "observed_inode": list(observed_inode) if observed_inode else None,
            "content_error": content_audit.get("error"),
        })
        last = dict(content_audit)
        last.update({
            "ok": ok, "owned_inode_match": owned,
            "expected_inode": list(expected_inode),
            "observed_inode": list(observed_inode) if observed_inode else None,
            "audit_attempts": attempt, "audit_maximum_attempts": maximum_attempts,
            "audit_attempt_log": attempts,
        })
        if ok:
            return last
    return last


def terminal_embedded_ownership_audit(path: Path) -> Dict[str, Any]:
    """Validate that a persisted terminal's embedded staging token owns its inode."""
    try:
        document, identity = read_regular_json_nofollow(path, include_inode=True)
        token = document.get("terminal_inode_ownership", {})
        token_inode = (int(token.get("device")), int(token.get("inode")))
        observed_inode = (int(identity["device"]), int(identity["inode"]))
        ok = (
            token.get("captured_from") == "O_EXCL-held staging fd before body write"
            and token.get("final_inode_must_match") is True
            and token_inode == observed_inode
            and identity["mode"] == "0444"
            and identity["nlink"] == 1
        )
        error = None
    except BaseException as exc:
        document = None
        identity = None
        token_inode = None
        observed_inode = None
        ok = False
        error = "{}: {}".format(type(exc).__name__, exc)
    return {
        "ok": ok, "identity": identity,
        "embedded_inode": list(token_inode) if token_inode else None,
        "observed_inode": list(observed_inode) if observed_inode else None,
        "error": error,
    }


def commit_terminal_document(path: Path, document: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atomically publish an exact terminal; the final path never exposes partial bytes.

    The semantic commit point is an exact, sealed, nofollow-audited final inode
    with link count one and no staging pathname.  A parent-directory fsync is
    attempted up to three times after that point.  Persistent directory-fsync
    failure is reported in the returned audit but cannot invert a committed
    PASS into process rc=1 (or a committed FAIL into any other return code).
    """
    global COMMITTED_RETURN_CODE, COMMITTED_STATUS
    if "terminal_inode_ownership" in document:
        raise ValueError("caller may not provide reserved terminal_inode_ownership")
    staging = terminal_staging_path(path)
    if lexical_exists(path) or lexical_exists(staging):
        raise FileExistsError("terminal final or staging path already exists")
    fd = -1
    publish_error: Optional[str] = None
    staging_inode: Optional[Tuple[int, int]] = None
    exception_reconciled = False
    exception_cleanup: Optional[Dict[str, Any]] = None
    rename_completed = False
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(staging), flags, 0o600)
        opened_info = os.fstat(fd)
        if not stat.S_ISREG(opened_info.st_mode) or opened_info.st_nlink != 1:
            raise ValueError("new terminal staging descriptor is not a single-link regular file")
        staging_inode = (int(opened_info.st_dev), int(opened_info.st_ino))
        committed_document = dict(document)
        committed_document["terminal_inode_ownership"] = {
            "device": staging_inode[0], "inode": staging_inode[1],
            "captured_from": "O_EXCL-held staging fd before body write",
            "final_inode_must_match": True,
        }
        payload = BASE.canonical_json_bytes(committed_document)
        terminal_write_all(fd, payload)
        terminal_set_readonly(fd)
        terminal_file_fsync(fd)
        sealed_info = os.fstat(fd)
        if (
            not stat.S_ISREG(sealed_info.st_mode)
            or (int(sealed_info.st_dev), int(sealed_info.st_ino)) != staging_inode
            or sealed_info.st_nlink != 1
            or stat.S_IMODE(sealed_info.st_mode) != 0o444
            or sealed_info.st_size != len(payload)
        ):
            raise ValueError("held terminal staging descriptor identity/seal changed")
        staging_audit = terminal_document_audit(staging, committed_document)
        if not staging_audit["ok"]:
            raise ValueError("terminal staging identity/content/seal audit failed")
        if tuple(staging_audit.get("observed_inode") or ()) != staging_inode:
            raise ValueError("terminal staging path no longer names the O_EXCL-opened inode")
        terminal_publish_noreplace(staging, path)
        rename_completed = True
        terminal_post_publish_hook()
    except BaseException as exc:
        publish_error = "{}: {}".format(type(exc).__name__, exc)
        # renameat2 success atomically removes staging.  Reconcile only when
        # the final name owns the exact staging dev/inode token and staging was
        # already absent before cleanup.  Identical foreign bytes after EEXIST
        # can therefore never be mistaken for this controller's publication.
        staging_absent_before_cleanup = not lexical_exists(staging)
        owned_audit = (
            terminal_owned_final_audit(path, committed_document, staging_inode)
            if staging_inode is not None and staging_absent_before_cleanup and lexical_exists(path)
            else {"ok": False, "owned_inode_match": False}
        )
        exception_reconciled = rename_completed and bool(owned_audit.get("ok")) and staging_absent_before_cleanup
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = -1
        exception_cleanup = terminal_cleanup_staging_with_retries(staging)
        if not exception_reconciled:
            terminal_parent_fsync_with_retries(path.parent)
            if not exception_cleanup["confirmed_absent"]:
                raise ValueError("terminal staging cleanup could not be confirmed before failure closeout")
            raise
    if staging_inode is None:
        raise ValueError("terminal staging ownership token was not established")
    try:
        commit_proof = terminal_owned_final_audit(path, committed_document, staging_inode)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = -1
    if not commit_proof["ok"] or lexical_exists(staging):
        raise ValueError("terminal final identity/content/seal or staging cleanup audit failed")
    # This is the irreversible semantic commit point.  All work below is
    # diagnostic/best-effort and must not cause outer failure closeout to
    # reclaim or contradict this exact owned terminal.
    COMMITTED_RETURN_CODE = int(document["return_code"])
    COMMITTED_STATUS = str(document.get("status", "COMMITTED_TERMINAL"))
    BASE.TERMINAL_COMMITTED = True
    durability = terminal_parent_fsync_with_retries(path.parent)
    post_commit_staging_cleanup = terminal_cleanup_staging_with_retries(staging)
    post_commit_observation = terminal_owned_final_audit(path, committed_document, staging_inode)
    try:
        embedded_ownership = terminal_embedded_ownership_audit(path)
    except BaseException as exc:
        embedded_ownership = {"ok": False, "error": "{}: {}".format(type(exc).__name__, exc)}
    audit = dict(commit_proof)
    audit.update({
        "atomic_staging_path": str(staging), "staging_absent": not lexical_exists(staging),
        "final_publish_method": "renameat2(RENAME_NOREPLACE)",
        "final_never_exposed_partial_bytes": True,
        "semantic_commit_point": "exact sealed path-bound nofollow final with dev/inode equal to held O_EXCL staging token, nlink=1, staging absent",
        "semantic_commit_point_reached": True,
        "owned_staging_inode": list(staging_inode),
        "owned_final_inode_match": bool(audit.get("owned_inode_match")),
        "embedded_ownership_token_matches_final": embedded_ownership["ok"],
        "reconciled_after_publish_exception": exception_reconciled,
        "renameat2_success_marker_set": rename_completed,
        "publish_exception": publish_error,
        "publish_exception_staging_cleanup": exception_cleanup,
        "parent_directory_fsync": durability,
        "directory_durability_confirmed": durability["confirmed"],
        "directory_durability_policy": "three attempts; report unconfirmed without changing the already committed document return_code",
        "post_commit_staging_cleanup": post_commit_staging_cleanup,
        "post_commit_observation": post_commit_observation,
        "post_commit_observation_confirmed": bool(post_commit_observation.get("ok")),
        "post_commit_observation_policy": "best-effort after semantic commit; cannot invert the committed document return_code",
    })
    identity = dict(audit["observed"])
    return identity, audit


def terminal_commit_public_audit(audit: Mapping[str, Any]) -> Dict[str, Any]:
    """Small stdout-safe audit for the already committed terminal document."""
    return {
        "semantic_commit_point_reached": bool(audit.get("semantic_commit_point_reached")),
        "staging_absent": bool(audit.get("staging_absent")),
        "reconciled_after_publish_exception": bool(audit.get("reconciled_after_publish_exception")),
        "owned_final_inode_match": bool(audit.get("owned_final_inode_match")),
        "embedded_ownership_token_matches_final": bool(audit.get("embedded_ownership_token_matches_final")),
        "post_commit_observation_confirmed": bool(audit.get("post_commit_observation_confirmed")),
        "post_commit_staging_absent": bool(audit.get("post_commit_staging_cleanup", {}).get("confirmed_absent")),
        "directory_durability_confirmed": bool(audit.get("directory_durability_confirmed")),
        "parent_directory_fsync": audit.get("parent_directory_fsync", {}),
    }


def safe_run_finalizers(snapshot: Optional[Mapping[str, Any]], previous_handlers: Mapping[int, Any]) -> Dict[str, Any]:
    """Never allow descriptor/signal restoration diagnostics to invert a terminal rc."""
    errors: List[str] = []
    for label, action in (
        ("close_held_snapshot", lambda: BASE.close_held_snapshot(snapshot)),
        ("restore_signal_handlers", lambda: BASE.restore_signal_handlers(previous_handlers)),
    ):
        try:
            action()
        except BaseException as exc:
            errors.append("{}:{}: {}".format(label, type(exc).__name__, exc))
    return {"ok": not errors, "errors": errors, "cannot_invert_committed_return_code": True}


def commit_terminal_and_return(path: Path, document: Mapping[str, Any]) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    return_code = int(document["return_code"])
    if return_code not in (0, 1):
        raise ValueError("terminal return_code must be 0 or 1")
    identity, audit = commit_terminal_document(path, document)
    BASE.TERMINAL_COMMITTED = True
    return return_code, identity, audit


def exact_directory_tree_audit(
    root: Path,
    expected_directories: Mapping[str, Mapping[str, Any]],
    expected_files: Sequence[str],
) -> Dict[str, Any]:
    """Audit one immutable tree without following directory or file symlinks."""
    actual_directories: Dict[str, Dict[str, Any]] = {}
    actual_files: List[str] = []
    type_failures: List[str] = []
    try:
        root_info = os.lstat(str(root))
        if not stat.S_ISDIR(root_info.st_mode):
            raise ValueError("tree root is not a real directory")
        for directory, child_directories, child_files in os.walk(str(root), topdown=True, followlinks=False):
            directory_path = Path(directory)
            relative_directory = "." if directory_path == root else str(directory_path.relative_to(root))
            info = os.lstat(str(directory_path))
            if not stat.S_ISDIR(info.st_mode):
                type_failures.append("directory:" + relative_directory)
            actual_directories[relative_directory] = {
                "device": info.st_dev, "inode": info.st_ino,
                "mode": format(stat.S_IMODE(info.st_mode), "04o"), "nlink": info.st_nlink,
            }
            for name in list(child_directories):
                path = directory_path / name
                child_info = os.lstat(str(path))
                if not stat.S_ISDIR(child_info.st_mode):
                    type_failures.append("directory:" + str(path.relative_to(root)))
            for name in child_files:
                path = directory_path / name
                child_info = os.lstat(str(path))
                relative_file = str(path.relative_to(root))
                if not stat.S_ISREG(child_info.st_mode):
                    type_failures.append("file:" + relative_file)
                actual_files.append(relative_file)
    except Exception as exc:
        return {
            "ok": False, "failures": ["{}: {}".format(type(exc).__name__, exc)],
            "actual_directories": actual_directories, "actual_files": sorted(actual_files),
        }
    expected_directory_names = sorted(expected_directories)
    directory_names_ok = sorted(actual_directories) == expected_directory_names
    file_names_ok = sorted(actual_files) == sorted(expected_files)
    directory_identities_ok = directory_names_ok and all(
        actual_directories[path] == {
            "device": int(spec["device"]), "inode": int(spec["inode"]),
            "mode": str(spec["mode"]), "nlink": int(spec["nlink"]),
        }
        for path, spec in expected_directories.items()
    )
    failures = list(type_failures)
    if not directory_names_ok:
        failures.append("exact_directory_set")
    if not file_names_ok:
        failures.append("exact_file_set")
    if not directory_identities_ok:
        failures.append("directory_identities")
    return {
        "ok": not failures, "failures": failures,
        "actual_directories": actual_directories, "actual_files": sorted(actual_files),
        "directory_names_ok": directory_names_ok, "file_names_ok": file_names_ok,
        "directory_identities_ok": directory_identities_ok,
    }


def expected_authority_fields() -> Dict[str, Any]:
    return {
        "schema_version": AUTHORITY_SCHEMA,
        "status": "AUTHORIZED_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START",
        "authorization_token_sha256": TOKEN_SHA256,
        "controller_command": CONTROLLER_COMMAND,
        "fresh_evidence_root": str(EVIDENCE_ROOT),
        "attempt": "attempt_002",
        "prior_global_evaluator_start_count": 1,
        "maximum_new_evaluator_starts": 1,
        "global_evaluator_start_count_after": 2,
        "retry_authorized": False,
        "root_confirmation": "ROOT_CONFIRMED_STAGE6_CORRECTIVE_ATTEMPT_002_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION",
        "claim_boundary": {
            "pure_existing_artifact_computation_only": True,
            "model_ros_publisher_or_trajectory_generation_authorized": False,
            "cross_system_metric_contrast_authorized": False,
            "performance_ordering_authorized": False,
            "inferential_statistics_authorized": False,
            "attempt_003_authorized": False,
            "next_stage_automatically_authorized": False,
        },
    }


def authority_schema_audit(document: Mapping[str, Any]) -> Dict[str, Any]:
    expected = expected_authority_fields()
    failures = [key for key, value in expected.items() if document.get(key) != value]
    if set(document) != set(expected) | AUTHORITY_IDENTITY_KEYS:
        failures.append("exact_top_level_allowlist")
    return {"ok": not failures, "failures": failures, "expected": expected}


def authority_audit(_lock: Mapping[str, Any]) -> Dict[str, Any]:
    if not lexical_exists(AUTHORITY):
        return {"present": False, "valid": False, "sealed": False, "failures": ["authority_absent"], "identity": None}
    failures: List[str] = []
    authority: Optional[Dict[str, Any]] = None
    identity: Optional[Dict[str, Any]] = None
    try:
        authority, identity = read_regular_json_nofollow(AUTHORITY)
        schema_audit = authority_schema_audit(authority)
        failures.extend(schema_audit["failures"])
        identity_paths = {
            "lock": LOCK, "protocol": ADDENDUM, "runner": RUNNER,
            "tests": TESTS, "test_receipt": TEST_RECEIPT,
            "failure_adoption": FAILURE_ADOPTION,
            "attempt_001_run_result": OLD_RUN_RESULT,
        }
        for key, path in identity_paths.items():
            if authority.get(key) != BASE.file_identity(path):
                failures.append(key)
        if identity["mode"] != "0444" or identity["nlink"] != 1:
            failures.append("seal")
    except Exception as exc:
        failures.append("{}: {}".format(type(exc).__name__, exc))
    return {
        "present": True, "valid": not failures,
        "sealed": bool(identity and identity.get("mode") == "0444" and identity.get("nlink") == 1),
        "failures": failures, "identity": identity,
    }


BASE.authority_audit = authority_audit


def attempt_001_adoption_audit() -> Dict[str, Any]:
    checks: Dict[str, bool] = {}
    details: Dict[str, Any] = {}
    failures: List[str] = []
    try:
        adoption, adoption_identity = read_regular_json_nofollow(FAILURE_ADOPTION)
        addendum, _addendum_identity = read_regular_json_nofollow(ADDENDUM)
        checks["adoption_sealed"] = adoption_identity["mode"] == "0444" and adoption_identity["nlink"] == 1
        checks["adoption_identity"] = all(
            adoption_identity[key] == addendum["attempt_001_failure_adoption"][expected_key]
            for key, expected_key in (("sha256", "sha256"), ("size_bytes", "size_bytes"))
        )
        checks["adoption_schema_status"] = (
            adoption.get("schema_version") == "aqua-fe-hfnet-supervins-mh01-common-support-attempt-001-failure-adoption-v1"
            and adoption.get("status") == "ADOPTED_IMMUTABLE_TERMINAL_FAIL_ATTEMPT_001"
        )
        checks["adoption_self_hash"] = adoption.get("self_hash") == BASE.self_hash_object(adoption)
        tree_spec = addendum["immutable_attempt_001_evidence"]
        tree_audit = exact_directory_tree_audit(
            OLD_EVIDENCE_ROOT,
            tree_spec["exact_directory_identities"],
            tree_spec["exact_regular_file_set"],
        )
        checks["attempt_001_exact_tree"] = tree_audit["ok"]
        checks["attempt_001_exact_file_set"] = tree_audit.get("file_names_ok", False)
        checks["attempt_001_exact_directory_set_and_identities"] = (
            tree_audit.get("directory_names_ok", False)
            and tree_audit.get("directory_identities_ok", False)
        )
        checks["attempt_001_analysis_bundle_absent"] = not any(
            path.startswith("attempt_001/analysis-output/")
            for path in tree_audit.get("actual_files", [])
        )
        observed: Dict[str, Any] = {}
        for key, spec in adoption["old_control_and_evidence_identities"].items():
            path = Path(spec["path"])
            observed[key] = BASE.file_identity(path, include_seal=True)
            if observed[key] != {name: spec[name] for name in ("sha256", "size_bytes", "mode", "nlink")}:
                failures.append("identity:" + key)
        checks["all_adopted_identities"] = not any(item.startswith("identity:") for item in failures)
        terminal, _terminal_identity = read_regular_json_nofollow(OLD_RUN_RESULT)
        claim, _claim_identity = read_regular_json_nofollow(OLD_START_CLAIM)
        checks["terminal_fail_exact"] = (
            terminal.get("status") == "FAIL_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS"
            and terminal.get("return_code") == 1
            and terminal.get("error", {}).get("message") == "forbidden comparison wording in reports: ['ratio']"
            and terminal.get("retry_authorized") is False
        )
        checks["old_start_consumed_once"] = (
            claim.get("evaluation_start_count_before") == 0
            and claim.get("evaluation_start_count_after") == 1
            and claim.get("maximum_evaluator_starts") == 1
            and claim.get("retry_authorized") is False
        )
        checks["old_terminal_pin_audits"] = (
            terminal.get("preflight_pin_snapshot", {}).get("ok") is True
            and terminal.get("held_snapshot_postflight", {}).get("ok") is True
            and terminal.get("post_pin_audit", {}).get("ok") is True
        )
        details = {
            "adoption_identity": adoption_identity, "attempt_001_tree_audit": tree_audit,
            "observed_identities": observed,
            "terminal_identity": BASE.file_identity(OLD_RUN_RESULT, include_seal=True),
            "burned_authority_identity": BASE.file_identity(OLD_AUTHORITY, include_seal=True),
        }
    except Exception as exc:
        failures.append("{}: {}".format(type(exc).__name__, exc))
    failures.extend(key for key, ok in checks.items() if not ok and key not in failures)
    return {"ok": not failures, "checks": checks, "failures": failures, "details": details}


def inherited_pin_audit(new_lock: Mapping[str, Any]) -> Dict[str, Any]:
    failures: List[str] = []
    try:
        old_lock, old_identity = read_regular_json_nofollow(OLD_LOCK)
        old_pins = old_lock["pinned_files"]
        new_pins = new_lock["pinned_files"]
        mismatches = [path for path, spec in old_pins.items() if new_pins.get(path) != spec]
        checks = {
            "old_lock_identity": old_identity,
            "old_pin_count": len(old_pins),
            "old_pin_digest": BASE.canonical_pin_digest(old_pins),
            "mismatches": mismatches,
        }
        if len(old_pins) != 31:
            failures.append("old_pin_count")
        if BASE.canonical_pin_digest(old_pins) != "9a9de036e3af55db187ff8d38f7b349e1969101525dc4b8b24864bee9ef07eee":
            failures.append("old_pin_digest")
        if mismatches:
            failures.append("old_pins_not_preserved")
    except Exception as exc:
        checks = {}
        failures.append("{}: {}".format(type(exc).__name__, exc))
    return {"ok": not failures, "failures": failures, "details": checks}


def collect_prestart(require_authority: bool = False) -> Dict[str, Any]:
    configure_base()
    base = BASE.collect_prestart(require_authority=require_authority)
    checks = dict(base.get("checks", {}))
    failures = list(base.get("failures", []))
    adoption = attempt_001_adoption_audit()
    try:
        new_lock, _lock_identity = read_regular_json_nofollow(LOCK)
        inherited = inherited_pin_audit(new_lock)
        checks["attempt_002_lock_lifecycle"] = (
            new_lock.get("attempt") == "attempt_002"
            and new_lock.get("prior_global_evaluator_start_count") == 1
            and new_lock.get("maximum_new_evaluator_starts") == 1
            and new_lock.get("global_evaluator_start_count_after") == 2
            and new_lock.get("retry_authorized") is False
            and new_lock.get("attempt_003_authorized") is False
        )
    except Exception as exc:
        inherited = {"ok": False, "failures": ["{}: {}".format(type(exc).__name__, exc)], "details": {}}
        checks["attempt_002_lock_lifecycle"] = False
    checks["attempt_001_failure_adoption_exact"] = adoption["ok"]
    checks["inherited_scientific_31_pins_exact"] = inherited["ok"]
    checks["fresh_attempt_002_root_lexically_absent"] = not lexical_exists(EVIDENCE_ROOT)
    checks["fresh_attempt_002_claim_lexically_absent"] = not lexical_exists(START_CLAIM)
    checks["renameat2_noreplace_terminal_publisher_available"] = _RENAMEAT2 is not None
    authority = authority_audit({})
    checks["attempt_002_authority_state"] = authority["valid"] if require_authority else not authority["present"]
    for key in (
        "attempt_002_lock_lifecycle", "attempt_001_failure_adoption_exact",
        "inherited_scientific_31_pins_exact", "fresh_attempt_002_root_lexically_absent",
        "fresh_attempt_002_claim_lexically_absent", "renameat2_noreplace_terminal_publisher_available",
        "attempt_002_authority_state",
    ):
        if not checks[key] and key not in failures:
            failures.append(key)
    failures.extend("adoption:" + value for value in adoption["failures"])
    failures.extend("inherited:" + value for value in inherited["failures"])
    failures = list(dict.fromkeys(failures))
    ready = not failures
    if ready and require_authority:
        status = "GO_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START"
    elif ready:
        status = "GO_AWAITING_SEPARATE_ROOT_AUTHORITY_FOR_CORRECTIVE_ATTEMPT_002"
    else:
        status = "NO_GO"
    base.update({
        "schema_version": "aqua-fe-hfnet-supervins-common-support-attempt-002-prestart-v1",
        "status": status, "ready": ready, "failures": failures,
        "check_count": len(checks), "checks": checks,
        "attempt_001_failure_adoption_audit": adoption,
        "inherited_scientific_pin_audit": inherited,
        "authority": authority,
        "attempt_002_lifecycle": {
            "prior_global_start_count": 1, "new_start_count_before": 0,
            "new_start_count_after": 1, "global_start_count_after": 2,
            "retry_authorized": False, "attempt_003_authorized": False,
        },
        "boundary": {
            "positions_parsed": False, "alignment_computed": False,
            "ape_computed": False, "rpe_computed": False,
            "subprocess_spawned": False, "ros_or_model_started": False,
            "attempt_001_modified": False,
        },
    })
    return base


def run_once(token: str) -> int:
    global COMMITTED_RETURN_CODE, COMMITTED_STATUS
    configure_base()
    COMMITTED_RETURN_CODE = None
    COMMITTED_STATUS = None
    if token != TOKEN:
        try:
            print(json.dumps({"status": "NO_GO", "error": "authorization token mismatch"}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 2
    preflight = collect_prestart(require_authority=True)
    if not preflight["ready"] or preflight["status"] != "GO_EXACTLY_ONE_CORRECTIVE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_002_START":
        try:
            print(json.dumps({"status": "NO_GO", "failures": preflight["failures"]}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 2

    previous_handlers = BASE.install_signal_handlers()
    snapshot: Optional[Dict[str, Any]] = None
    started_at = BASE.now_iso()
    try:
        BASE.create_owned_evidence_root()
        BASE.mkdir_exclusive_durable(ATTEMPT)
        BASE.raise_if_pending()
        claim = {
            "schema_version": "aqua-fe-hfnet-supervins-common-support-attempt-002-start-claim-v1",
            "created_at": BASE.now_iso(), "attempt": "attempt_002",
            "prior_global_evaluation_start_count": 1,
            "attempt_002_start_count_before": 0, "attempt_002_start_count_after": 1,
            "global_evaluation_start_count_after": 2,
            "maximum_new_evaluator_starts": 1, "retry_authorized": False,
            "controller_command": CONTROLLER_COMMAND,
            "authorization_token_sha256": TOKEN_SHA256,
            "protocol": BASE.file_identity(ADDENDUM), "lock": BASE.file_identity(LOCK),
            "authority": BASE.file_identity(AUTHORITY), "runner": BASE.file_identity(RUNNER),
            "tests": BASE.file_identity(TESTS), "test_receipt": BASE.file_identity(TEST_RECEIPT),
            "failure_adoption": BASE.file_identity(FAILURE_ADOPTION),
            "attempt_001_run_result": BASE.file_identity(OLD_RUN_RESULT),
            "boundary": {
                "corrective_pure_existing_artifact_computation_only": True,
                "subprocess_ros_model_publisher_or_trajectory_generation": False,
                "cross_system_metric_contrast": False,
                "performance_ordering": False,
                "attempt_003_authorized": False,
            },
        }
        BASE.write_json_exclusive(START_CLAIM, claim)
        BASE.raise_if_pending()
        BASE.write_json_exclusive(PREFLIGHT_RESULT, preflight)
        BASE.mkdir_exclusive_durable(ANALYSIS)
        BASE.mkdir_exclusive_durable(FIGURES)
        BASE.raise_if_pending()

        pins = BASE.load_json(LOCK)["pinned_files"]
        snapshot = BASE.held_snapshot_open(BASE.SNAPSHOT_PATHS, pins)
        payloads = snapshot["records"]
        get_payload = lambda path: payloads[str(path.resolve())]["payload"]
        timestamp_support = BASE.support_audit_from_bytes(
            get_payload(BASE.HF_TRAJECTORY), get_payload(BASE.SV_TRAJECTORY),
            get_payload(BASE.CAMERA_CSV), get_payload(BASE.GT_CSV),
        )
        if not timestamp_support["ok"]:
            raise ValueError("authorized held-snapshot timestamp support failed")
        evaluation = BASE.generate_analysis_bundle(snapshot, timestamp_support)
        BASE.raise_if_pending()

        held_post = BASE.held_snapshot_postflight(snapshot, pins)
        if not held_post["ok"]:
            raise ValueError("held descriptor/path postflight failed")
        post_pins = BASE.post_pin_audit(preflight)
        if not post_pins["ok"]:
            raise ValueError("postflight pin audit failed")
        adoption_post = attempt_001_adoption_audit()
        if not adoption_post["ok"]:
            raise ValueError("attempt_001 failure adoption changed")
        bundle_audit = BASE.audit_completed_bundle(evaluation["bundle_artifacts"])
        if not bundle_audit["ok"]:
            raise ValueError("strict bundle audit failed")
        relevant = BASE.relevant_processes()
        children = BASE.direct_child_processes()
        if relevant or children:
            raise ValueError("relevant generator or evaluator child process observed")
        authority_post = authority_audit(BASE.load_json(LOCK))
        if not authority_post["valid"] or authority_post.get("identity") != preflight["authority"].get("identity"):
            raise ValueError("attempt_002 root authority changed or became invalid")
        figures = evaluation["figure_audits"]
        pass_conditions = {
            "preflight_go_with_new_root_authority": True,
            "attempt_001_failure_adoption_unchanged": adoption_post["ok"],
            "global_lifecycle_one_to_two_exactly_one_new_start_no_retry": True,
            "held_descriptor_snapshots_and_postflight_paths_match": held_post["ok"],
            "all_inherited_and_additive_pins_unchanged": post_pins["ok"],
            "new_root_authority_identity_unchanged_and_valid": authority_post["valid"] and authority_post.get("identity") == preflight["authority"].get("identity"),
            "identical_exact_gt_common_support_1358_each": evaluation["support_audit"]["counts"]["common"] == BASE.COMMON_COUNT,
            "exact_one_second_pairs_1348_each": evaluation["support_audit"]["counts"]["rpe_pairs"] == BASE.RPE_COUNT,
            "independent_fixed_scale_proper_se3": all(evaluation["alignment"][system]["primary_fixed_scale_se3"]["proper"] for system in ("hfnet", "supervins")),
            "independent_positive_scale_proper_sim3_diagnostic": all(evaluation["alignment"][system]["secondary_sim3_scale_diagnostic"]["proper"] for system in ("hfnet", "supervins")),
            "frozen_core_coordinate_crosschecks": all(evaluation["alignment"][system]["primary_fixed_scale_se3"]["core_crosscheck_max_abs_m"] <= 1e-12 for system in ("hfnet", "supervins")),
            "all_metric_values_finite_nonnegative_and_counts_exact": BASE.metrics_finite_nonnegative(evaluation["metrics"]),
            "whole_token_report_lexer_passed": evaluation["report_boundary_audit"]["ok"] and evaluation["report_boundary_audit"]["substring_matching_used"] is False,
            "cross_system_metric_contrast_and_ordering_absent": evaluation["metrics"]["statistical_boundary"]["cross_system_metric_contrast_computed"] is False and evaluation["metrics_schema_audit"]["ok"],
            "coverage_failure_prefix_and_output_semantics_disclosed": evaluation["input_audit"]["semantic_non_equivalence_disclosed"],
            "bundle_complete_manifested_tree_and_self_hashed": bundle_audit["ok"],
            "trajectory_figure_equal_metric_aspect_and_shared_domain": figures["figure_01"]["equal_metric_aspect_all_axes"],
            "error_figure_axes_lower_zero": figures["figure_02"]["all_axis_lower_bounds_exact_zero"],
            "figure_gridline_coordinates_valid": figures["figure_01"]["gridline_coordinates_valid"] and figures["figure_02"]["gridline_coordinates_valid"],
            "no_subprocess_ros_model_publisher_or_trajectory_generation": not relevant and not children,
        }
        if not all(pass_conditions.values()):
            raise ValueError("terminal pass condition failed")
        artifacts = BASE.inventory_attempt_files(exclude_result=True)
        result = {
            "schema_version": RESULT_SCHEMA,
            "status": "PASS_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS_ATTEMPT_002_CORRECTIVE",
            "return_code": 0, "started_at": started_at, "completed_at": BASE.now_iso(),
            "authorization": {
                "prior_global_evaluation_start_count": 1,
                "attempt_002_evaluation_start_count": 1,
                "global_evaluation_start_count_after": 2,
                "retry_authorized": False,
                "root_execution_authority": BASE.file_identity(AUTHORITY, include_seal=True),
            },
            "pass_conditions": pass_conditions, "metrics": evaluation["metrics"],
            "support_audit": evaluation["support_audit"], "alignment": evaluation["alignment"],
            "figure_audits": figures, "bundle_audit": bundle_audit,
            "report_boundary_audit": evaluation["report_boundary_audit"],
            "metrics_schema_audit": evaluation["metrics_schema_audit"],
            "attempt_001_failure_adoption_preflight": preflight["attempt_001_failure_adoption_audit"],
            "attempt_001_failure_adoption_postflight": adoption_post,
            "held_snapshot_postflight": held_post, "post_pin_audit": post_pins,
            "root_authority_preflight": preflight["authority"], "root_authority_postflight": authority_post,
            "relevant_processes_at_closeout": relevant, "direct_child_processes_at_closeout": children,
            "artifact_count_before_result": len(artifacts), "artifacts": artifacts,
            "claim_boundary": {
                "artifact_level_exact_common_tail_description_only": True,
                "cross_system_metric_contrast": False, "performance_ordering": False,
                "inferential_statistics": False, "model_or_ros_rerun": False,
                "equivalent_initialization_or_output_semantics": False,
                "attempt_001_scientific_values_used": False,
                "readme_v2_01_underwater_or_generalization": False,
                "attempt_003_authorized": False,
            },
            "terminal_publication_contract": {
                "atomic_noreplace_method": "renameat2(RENAME_NOREPLACE)",
                "final_path_never_exposes_partial_bytes": True,
                "semantic_commit_point": "exact sealed path-bound nofollow final with embedded dev/inode equal to held O_EXCL staging token, nlink=1, staging absent",
                "adoption_requires_observed_process_return_code_and_stdout_commit_audit": True,
                "parent_directory_fsync_attempts": 3,
                "directory_durability_outcome_emitted_on_stdout": True,
                "terminal_json_claims_parent_directory_crash_durability": False,
                "committed_document_return_code_never_inverted_by_post_commit_directory_fsync_error": True,
            },
            "next_stage_automatically_authorized": False,
        }
        BASE.raise_if_pending()
        return_code, result_identity, _terminal_commit_audit = commit_terminal_and_return(RUN_RESULT, result)
        try:
            print(json.dumps({
                "status": result["status"], "return_code": return_code,
                "run_result_identity": result_identity,
                "terminal_commit_audit": terminal_commit_public_audit(_terminal_commit_audit),
            }, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return return_code
    except BaseException as exc:
        if BASE.TERMINAL_COMMITTED and COMMITTED_RETURN_CODE in (0, 1):
            committed_return_code = int(COMMITTED_RETURN_CODE)
            try:
                print(json.dumps({
                    "status": COMMITTED_STATUS,
                    "return_code": committed_return_code,
                    "post_commit_exception_ignored": "{}: {}".format(type(exc).__name__, exc),
                    "semantic_commit_point_precedes_this_exception": True,
                }, sort_keys=True))
            except (BrokenPipeError, OSError):
                pass
            return committed_return_code
        failure_return_code = 1
        uncommitted_reclaim: Optional[Dict[str, Any]] = None
        if BASE.ensure_failure_namespace() and not BASE.TERMINAL_COMMITTED:
            uncommitted_reclaim = reclaim_uncommitted_terminal_paths(RUN_RESULT)
        if (
            BASE.NAMESPACE_OWNED
            and not BASE.TERMINAL_COMMITTED
            and uncommitted_reclaim is not None
            and uncommitted_reclaim["ok"]
            and not lexical_exists(RUN_RESULT)
            and not lexical_exists(terminal_staging_path(RUN_RESULT))
        ):
            failure = {
                "schema_version": RESULT_SCHEMA,
                "status": "FAIL_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS_ATTEMPT_002_CORRECTIVE",
                "return_code": 1, "started_at": started_at, "completed_at": BASE.now_iso(),
                "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()},
                "pending_signal": BASE.PENDING_SIGNAL, "retry_authorized": False,
                "prior_global_evaluation_start_count": 1,
                "global_evaluation_start_count_after_this_start": 2,
                "preflight_pin_snapshot": preflight.get("pin_snapshot", {}),
                "attempt_001_failure_adoption_preflight": preflight.get("attempt_001_failure_adoption_audit", {}),
                "attempt_001_failure_adoption_postflight": BASE.best_effort(attempt_001_adoption_audit, {"ok": False, "checks": {}, "failures": []}),
                "held_snapshot_postflight": BASE.best_effort(lambda: BASE.held_snapshot_postflight(snapshot or {}, BASE.load_json(LOCK)["pinned_files"]), {"ok": False, "checks": {}, "failures": []}),
                "post_pin_audit": BASE.best_effort(lambda: BASE.post_pin_audit(preflight), {"ok": False, "checks": {}, "failures": []}),
                "artifacts_before_result": BASE.best_effort(lambda: BASE.inventory_attempt_files(exclude_result=True), {}),
                "uncommitted_terminal_reclaim": uncommitted_reclaim,
                "claim_boundary": {
                    "scientific_metrics_may_be_used": False,
                    "model_or_ros_rerun": False,
                    "retry_authorized": False,
                    "attempt_003_authorized": False,
                },
                "terminal_publication_contract": {
                    "atomic_noreplace_method": "renameat2(RENAME_NOREPLACE)",
                    "final_path_never_exposes_partial_bytes": True,
                    "semantic_commit_point": "exact sealed path-bound nofollow final with embedded dev/inode equal to held O_EXCL staging token, nlink=1, staging absent",
                    "adoption_requires_observed_process_return_code_and_stdout_commit_audit": True,
                    "parent_directory_fsync_attempts": 3,
                    "directory_durability_outcome_emitted_on_stdout": True,
                    "terminal_json_claims_parent_directory_crash_durability": False,
                    "committed_document_return_code_never_inverted_by_post_commit_directory_fsync_error": True,
                },
            }
            failure_commit_audit: Optional[Dict[str, Any]] = None
            try:
                failure_return_code, _failure_identity, failure_commit_audit = commit_terminal_and_return(RUN_RESULT, failure)
            except Exception:
                pass
        try:
            message: Dict[str, Any] = {
                "status": "FAIL", "return_code": failure_return_code,
                "error": "{}: {}".format(type(exc).__name__, exc),
            }
            if "failure_commit_audit" in locals() and failure_commit_audit is not None:
                message["terminal_commit_audit"] = terminal_commit_public_audit(failure_commit_audit)
            print(json.dumps(message, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return failure_return_code
    finally:
        finalizer_audit = safe_run_finalizers(snapshot, previous_handlers)
        if not finalizer_audit["ok"]:
            try:
                print(json.dumps({"post_terminal_finalizer_audit": finalizer_audit}, sort_keys=True))
            except (BrokenPipeError, OSError):
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args(argv)
    if args.action == "preflight":
        result = collect_prestart(require_authority=False)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["ready"] else 2
    return run_once(args.authorization_token)


if __name__ == "__main__":
    raise SystemExit(main())
