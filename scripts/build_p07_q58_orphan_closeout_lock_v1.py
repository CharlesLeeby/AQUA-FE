#!/usr/bin/env python3
"""Freeze queue 58 after its orphaned physical export finishes.

The original v5 executor appended the canonical RUNNING event before its
supervisor disappeared.  Because the physical command was started in a new
session, it may finish without the Python executor.  This lock is deliberately
post-command and pre-attestation/audit: it binds the preserved attempt and run
bytes so a later closeout can perform only the post-child steps from the frozen
v5 executor.  It never executes the frontend and never edits the registry.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_export_job_v5 as v5
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
    from scripts import run_p07_q55_a04_layout_replacement_v1 as correction_runtime
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_export_job_v5 as v5  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore
    import run_p07_q55_a04_layout_replacement_v1 as correction_runtime  # type: ignore


QUEUE_INDEX = 58
TAG = "isj_p07_aqualoc_archaeology_a07_0001_m_attempt01"
ATTEMPT = governance.P07 / f"frontend_attempts/queue_058_{TAG}"
RUN_DIR = (
    governance.ROOT
    / "logs/aqualoc_archaeo_vins"
    / f"external_xfeat_every2_{TAG}"
)
FEATURE_BAG = RUN_DIR / "features.bag"
RAW_BAG = governance.ROOT / "datasets/aqualoc/rosbags/archaeo07_900_1800.bag"
RECOVERY_ROOT = governance.P07 / "frontend_orphan_recoveries"
OUTPUT = RECOVERY_ROOT / "queue_058_orphan_closeout_lock_v1.json"
CLOSEOUT = ATTEMPT / "orphan_execution_closeout_v1.json"
OUTPUT_MANIFEST = ATTEMPT / "output_hash_manifest.sha256"
ATTESTATION = Path(str(FEATURE_BAG) + ".p05-xfeat-contract.json")
AUDIT = ATTEMPT / "audit_v4.json"
AUDIT_LOG = ATTEMPT / "audit_v4.log"
ATTESTATION_LOG = ATTEMPT / "attestation.log"

SCHEMA = "isj-p07-q58-orphan-closeout-lock-v1"
STATUS = "FROZEN_POST_PHYSICAL_COMMAND_PRE_ATTESTATION_AUDIT"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"

REQUIRED_Q55_BINDINGS = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_replacements/"
    "queue_055_a04_d_path_correction_lock_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/frontend_replacements/"
    "queue_055_a04_layout_attempt02_closeout_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/d_resolution_locks/"
    "aqualoc_archaeology_a04_0002_v4.json",
    "papers/ieee_sensors_journal_experiments/p07/d_resolutions/"
    "aqualoc_archaeology_a04_0002_not_applicable_v2.json",
)

# These are the post-child adapters plus their direct/transitive auditors and
# attester.  The q58 input manifest contributes the full producer-side closure.
TRANSITIVE_POST_CHILD_FILES = (
    governance.ROOT / "scripts/build_p07_q58_orphan_closeout_lock_v1.py",
    governance.ROOT / "scripts/closeout_p07_q58_orphan_execution_v1.py",
    governance.ROOT / "scripts/tests/test_p07_q58_orphan_closeout_v1.py",
    governance.ROOT / "scripts/run_p07_frontend_export_job_v5.py",
    governance.ROOT / "scripts/run_p07_frontend_export_job_v4.py",
    governance.ROOT / "scripts/run_p07_frontend_export_job_v3.py",
    governance.ROOT / "scripts/run_p07_mp_frontend_export_job_v2.py",
    governance.ROOT / "scripts/run_p07_q55_a04_layout_replacement_v1.py",
    governance.ROOT / "scripts/build_p07_q55_a04_layout_replacement_lock_v1.py",
    governance.ROOT / "scripts/reclaim_p07_raw_cache_v1.py",
    governance.ROOT / "scripts/resolve_p07_d_applicability_v3.py",
    governance.ROOT / "scripts/resolve_p07_d_applicability_v4.py",
    governance.ROOT / "scripts/run_p07_frontend_queue_v6.py",
    governance.ROOT / "scripts/audit_p07_frontend_export_v4.py",
    governance.ROOT / "scripts/audit_p07_frontend_export_v3.py",
    governance.ROOT / "scripts/audit_p07_mp_frontend_export_v2.py",
    governance.ROOT / "scripts/attest_p05_xfeat_feature_bag_v1.py",
    governance.ROOT / "scripts/build_nativeq_backend_contract.py",
    governance.ROOT / "scripts/check_nativeq_backend_contract.py",
    governance.ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py",
    governance.ROOT / "scripts/build_p07_preoutcome_governance_v1.py",
    governance.EXPORT_QUEUE,
    governance.ALLOCATION_CSV,
    governance.P07 / "frontend_execution_correction_lock_v5.json",
)


class OrphanCloseoutViolation(RuntimeError):
    """Fail-closed violation of the queue-58 orphan recovery contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hash(payload: dict[str, Any], field: str = "closeout_lock_hash") -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(
        json.dumps(
            clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    path = auditor.lexical_absolute(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def prefix_snapshot(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": auditor.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _process_matches_q58(parts: list[str]) -> bool:
    joined = "\0".join(parts)
    expected_paths = (str(RAW_BAG), str(FEATURE_BAG), TAG)
    if any(value in joined for value in expected_paths):
        return True
    runner = "run_aqualoc_archaeo_vins_eval.sh"
    expected_tail = ["external", "7", "900", "1800", "xfeat", "2"]
    return any(part.endswith(runner) for part in parts) and parts[-6:] == expected_tail


def active_q58_processes(
    proc_root: Path = Path("/proc"), *, own_pid: int | None = None
) -> list[dict[str, Any]]:
    """Return live processes attributable to the exact frozen q58 command."""

    own_pid = os.getpid() if own_pid is None else own_pid
    active: list[dict[str, Any]] = []
    try:
        process_dirs = list(proc_root.iterdir())
    except OSError as error:
        raise OrphanCloseoutViolation(f"cannot inspect process table: {error}") from error
    for process_dir in process_dirs:
        if not process_dir.name.isdigit() or int(process_dir.name) == own_pid:
            continue
        try:
            raw = (process_dir / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if parts and _process_matches_q58(parts):
            active.append({"pid": int(process_dir.name), "cmdline": parts})
    return sorted(active, key=lambda item: int(item["pid"]))


def parse_hash_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise OrphanCloseoutViolation(f"missing q58 input hash manifest: {path}")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            raise OrphanCloseoutViolation(
                f"invalid input manifest line {line_number}: {line!r}"
            )
        expected, raw_path = line.split("  ", 1)
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise OrphanCloseoutViolation(
                f"invalid input manifest digest on line {line_number}"
            )
        if raw_path in seen:
            raise OrphanCloseoutViolation(f"duplicate input manifest path: {raw_path}")
        seen.add(raw_path)
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = governance.ROOT / candidate
        candidate = auditor.lexical_absolute(candidate)
        if not candidate.is_file() or sha256(candidate) != expected:
            raise OrphanCloseoutViolation(f"q58 input manifest artifact drift: {candidate}")
        records.append(
            {
                "path": auditor.display_path(candidate),
                "sha256": expected,
                "size_bytes": candidate.stat().st_size,
            }
        )
    if not records:
        raise OrphanCloseoutViolation("q58 input hash manifest is empty")
    missing = sorted(set(REQUIRED_Q55_BINDINGS) - {item["path"] for item in records})
    if missing:
        raise OrphanCloseoutViolation(
            f"q58 input manifest lacks q55 replacement/D bindings: {missing}"
        )
    return records


def validate_q55_binding_documents() -> dict[str, Any]:
    documents = {
        path: json.loads((governance.ROOT / path).read_text(encoding="utf-8"))
        for path in REQUIRED_Q55_BINDINGS
    }
    correction = documents[REQUIRED_Q55_BINDINGS[0]]
    replacement = documents[REQUIRED_Q55_BINDINGS[1]]
    d_lock = documents[REQUIRED_Q55_BINDINGS[2]]
    d_resolution = documents[REQUIRED_Q55_BINDINGS[3]]
    if (
        correction.get("schema_version") != "isj-p07-a04-d-path-correction-lock-v1"
        or correction.get("status") != "FROZEN_READY_FOR_A04_D_PATH_CORRECTION"
        or correction.get("window_id") != "aqualoc_archaeology:A04:0002"
    ):
        raise OrphanCloseoutViolation("q55 D-path correction lock is not exact")
    if (
        replacement.get("schema_version")
        != "isj-p07-frontend-layout-replacement-closeout-v1"
        or replacement.get("status") != "PASS"
        or replacement.get("original_queue_index") != 55
        or replacement.get("effective_slot_status") != "COMPLETED"
        or replacement.get("physical_frontend_rerun") is not True
        or replacement.get("trajectory_outcome_read") is not False
    ):
        raise OrphanCloseoutViolation("q55 replacement closeout is not exact")
    if (
        d_lock.get("schema_version") != "isj-p07-d-resolution-lock-v4"
        or d_lock.get("status") != "FROZEN_READY_TO_RESOLVE_D"
        or d_lock.get("window_id") != "aqualoc_archaeology:A04:0002"
    ):
        raise OrphanCloseoutViolation("q55 D-resolution lock is not exact")
    if (
        d_resolution.get("schema_version")
        != "isj-p07-d-applicability-resolution-v2"
        or d_resolution.get("status") != "PASS_NOT_APPLICABLE"
        or d_resolution.get("resolution") != "NOT_APPLICABLE"
        or d_resolution.get("window_id") != "aqualoc_archaeology:A04:0002"
    ):
        raise OrphanCloseoutViolation("q55 terminal D resolution is not exact")
    return {
        "replacement_closeout_hash": replacement.get("closeout_hash"),
        "d_resolution_status": d_resolution["status"],
        "d_resolution": d_resolution["resolution"],
    }


def validate_registry_chain(
    chain: list[dict[str, str]], run_id: str
) -> tuple[dict[str, str], dict[str, str]]:
    if len(chain) != 2:
        raise OrphanCloseoutViolation(
            f"q58 registry chain is not exact e00/e01: {[row.get('status') for row in chain]}"
        )
    e00, e01 = chain
    expected = (
        (e00, f"{run_id}_e00", "", "PLANNED"),
        (e01, f"{run_id}_e01", f"{run_id}_e00", "RUNNING"),
    )
    for row, event_id, parent, status in expected:
        if (
            row.get("run_id") != run_id
            or row.get("registry_event_id") != event_id
            or row.get("supersedes_event_id") != parent
            or row.get("status") != status
        ):
            raise OrphanCloseoutViolation(
                f"q58 registry event mismatch at {event_id}: {row}"
            )
    expected_command = auditor.display_path(ATTEMPT / "command.txt")
    expected_input = auditor.display_path(ATTEMPT / "input_hash_manifest.sha256")
    expected_e00_command = auditor.display_path(governance.EXPORT_QUEUE)
    expected_e00_run = auditor.display_path(RUN_DIR)
    expected_e01_run = auditor.display_path(governance.ROOT / "logs/aqualoc_archaeo_vins")
    if (
        e00.get("command_file") != expected_e00_command
        or e00.get("run_dir") != expected_e00_run
        or e00.get("output_hash_manifest") not in {None, ""}
        or e01.get("command_file") != expected_command
        or e01.get("input_hash_manifest") != expected_input
        or e01.get("output_hash_manifest") not in {None, ""}
        or e01.get("run_dir") != expected_e01_run
        or e01.get("infrastructure_failure") not in {None, ""}
    ):
        raise OrphanCloseoutViolation("q58 e01 does not bind the preserved attempt")
    required_notes = (
        "generalized v3 no-clobber executor started queue_index=58",
        "guard-only preflight exact PASS",
        "predecessor queue_index=55 satisfied by additive replacement",
        "canonical q55 remains FAILED",
    )
    if any(fragment not in e01.get("notes", "") for fragment in required_notes):
        raise OrphanCloseoutViolation(
            "q58 e01 lacks the frozen executor/q55 predecessor notes"
        )
    return e00, e01


def completion_markers(row: dict[str, str]) -> dict[str, Any]:
    if not row["command"].startswith("RUN_VINS=0 "):
        raise OrphanCloseoutViolation("q58 frozen command is not RUN_VINS=0")
    observed = hashlib.sha256(row["command"].encode("utf-8")).hexdigest()
    if observed != row["command_sha256"]:
        raise OrphanCloseoutViolation("q58 frozen command hash mismatch")
    command_path = ATTEMPT / "command.txt"
    if command_path.read_text(encoding="utf-8") != row["command"] + "\n":
        raise OrphanCloseoutViolation("q58 attempt command differs from frozen queue")
    command_log = ATTEMPT / "command.log"
    text = command_log.read_text(encoding="utf-8", errors="replace")
    expected_tail = (
        f"RUN_VINS=0, skipping VINS for {RUN_DIR}\n"
        f"run_dir={RUN_DIR}\n"
        f"raw_bag={RAW_BAG}\n"
        f"play_bag={FEATURE_BAG}\n"
    )
    if not text.endswith(expected_tail):
        raise OrphanCloseoutViolation("q58 command log lacks exact terminal success markers")
    required_guard = "P05 XFeat backend contract PASS"
    if required_guard not in text or "contract rejected M" in text:
        raise OrphanCloseoutViolation("q58 command log does not prove exact M guard PASS")
    guard_path = auditor.parse_guard_path(command_log)
    guard = auditor.validate_guard(guard_path, governance.M_ARM)
    return {
        "command_log": file_record(command_log),
        "terminal_tail_sha256": hashlib.sha256(expected_tail.encode("utf-8")).hexdigest(),
        "terminal_markers_exact": True,
        "direct_returncode_observed": False,
        "guard": {
            "path": auditor.display_path(guard_path),
            "sha256": sha256(guard_path),
            "schema_version": guard["schema_version"],
            "action": guard["action"],
        },
    }


def validate_preserved_run(row: dict[str, str]) -> tuple[list[Path], dict[str, Any]]:
    if row["arm"] != governance.M_ARM:
        raise OrphanCloseoutViolation(f"q58 is not frozen M: {row['arm']}")
    expected_feature = auditor.lexical_absolute(governance.ROOT / row["expected_feature_bag"])
    if expected_feature != auditor.lexical_absolute(FEATURE_BAG):
        raise OrphanCloseoutViolation("q58 expected feature bag path mismatch")
    required = (
        FEATURE_BAG,
        RUN_DIR / "frontend_metrics.csv",
        RUN_DIR / "aqualoc_archaeo07_pinhole.yaml",
    )
    for path in required:
        if not path.is_file() or path.stat().st_size <= 0:
            raise OrphanCloseoutViolation(f"missing or empty q58 run artifact: {path}")
    if not RAW_BAG.is_file() or RAW_BAG.stat().st_size <= 0:
        raise OrphanCloseoutViolation(f"missing or empty q58 raw cache: {RAW_BAG}")
    vins_output = RUN_DIR / "vins_output"
    if not vins_output.is_dir() or any(path.is_file() for path in vins_output.rglob("*")):
        raise OrphanCloseoutViolation("q58 RUN_VINS=0 output directory is absent or non-empty")
    forbidden = auditor.forbidden_outcomes([RUN_DIR])
    if forbidden:
        raise OrphanCloseoutViolation(f"q58 contains forbidden trajectory outcomes: {forbidden}")
    run_files = sorted(
        (path for path in RUN_DIR.rglob("*") if path.is_file()), key=lambda path: str(path)
    )
    if set(required) - set(run_files):
        raise OrphanCloseoutViolation("q58 run tree is structurally incomplete")
    return run_files, {
        "run_dir": auditor.display_path(RUN_DIR),
        "run_file_count": len(run_files),
        "vins_output_empty": True,
        "forbidden_trajectory_outcomes": [],
        "ephemeral_raw_cache": file_record(RAW_BAG),
    }


def postprocess_paths() -> tuple[Path, ...]:
    return (
        ATTESTATION,
        ATTESTATION_LOG,
        AUDIT,
        AUDIT_LOG,
        OUTPUT_MANIFEST,
        CLOSEOUT,
    )


def assert_postprocess_absent() -> None:
    collisions = [path for path in postprocess_paths() if path.exists()]
    partials: list[Path] = []
    for path in (*postprocess_paths(), OUTPUT):
        if path.parent.is_dir():
            partials.extend(path.parent.glob(f"{path.name}.partial.*"))
    if OUTPUT.exists():
        collisions.append(OUTPUT)
    if collisions or partials:
        raise FileExistsError(
            f"q58 orphan closeout no-clobber collision: "
            f"complete={sorted(map(str, collisions))} partial={sorted(map(str, partials))}"
        )


def _deduplicated_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    unique = sorted(
        {auditor.lexical_absolute(path) for path in paths}, key=lambda path: str(path)
    )
    return [file_record(path) for path in unique]


def build_lock() -> dict[str, Any]:
    assert_postprocess_absent()
    active = active_q58_processes()
    if active:
        raise OrphanCloseoutViolation(f"q58 physical process is still active: {active}")

    row = auditor.queue_row(QUEUE_INDEX)
    allocation = auditor.allocation_row(QUEUE_INDEX)
    chain = registry.registry_chain(allocation["run_id"])
    e00, e01 = validate_registry_chain(chain, allocation["run_id"])
    input_manifest = ATTEMPT / "input_hash_manifest.sha256"
    input_records = parse_hash_manifest(input_manifest)
    q55_binding = validate_q55_binding_documents()
    completion = completion_markers(row)
    run_files, run_summary = validate_preserved_run(row)

    attempt_files = sorted(
        (path for path in ATTEMPT.iterdir() if path.is_file()), key=lambda path: str(path)
    )
    expected_attempt_names = {
        "capacity_preflight.json",
        "command.log",
        "command.txt",
        "guard_preflight_command.txt",
        "guard_preflight.log",
        "input_hash_manifest.sha256",
    }
    if {path.name for path in attempt_files} != expected_attempt_names:
        raise OrphanCloseoutViolation(
            "q58 attempt is not the exact pre-postprocess file set: "
            f"{sorted(path.name for path in attempt_files)}"
        )
    actual_guard = governance.ROOT / completion["guard"]["path"]
    preflight_guard = auditor.parse_guard_path(ATTEMPT / "guard_preflight.log")
    auditor.validate_guard(preflight_guard, governance.M_ARM)

    bound_paths = [
        *TRANSITIVE_POST_CHILD_FILES,
        *[governance.ROOT / item["path"] for item in input_records],
        *attempt_files,
        *run_files,
        actual_guard,
        preflight_guard,
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "queue_index": QUEUE_INDEX,
        "run_id": allocation["run_id"],
        "arm": row["arm"],
        "tag": row["tag"],
        "command": row["command"],
        "command_sha256": row["command_sha256"],
        "orphan_class": "OUTER_EXECUTOR_TERMINATED_CHILD_SESSION_PRESERVED",
        "canonical_registry_state": {
            "e00": e00,
            "e01": e01,
            "required_closeout_transition": "RUNNING_e01_TO_COMPLETED_e02",
            "fabricate_failed_event": False,
        },
        "physical_command_completion": completion,
        "preserved_run": run_summary,
        "q55_replacement_and_d_predecessor_binding": q55_binding,
        "input_manifest_verified_artifacts": input_records,
        "artifacts": _deduplicated_records(bound_paths),
        "mutable_stream_prefix_snapshots": [prefix_snapshot(registry.RUN_REGISTRY)],
        "required_closeout": {
            "adapter": "scripts/run_p07_frontend_export_job_v5.py",
            "attester": "scripts/attest_p05_xfeat_feature_bag_v1.py",
            "auditor": "scripts/audit_p07_frontend_export_v4.py",
            "output_manifest": auditor.display_path(OUTPUT_MANIFEST),
            "closeout": auditor.display_path(CLOSEOUT),
            "physical_frontend_rerun": False,
            "on_pass_registry_transition": "append_e02_COMPLETED_from_e01_RUNNING",
        },
        "physical_frontend_rerun": False,
        "held_out_frontend_outcome_read_before_lock": False,
        "trajectory_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload["closeout_lock_hash"] = document_hash(payload)
    return payload


def atomic_write_json_no_clobber(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or list(path.parent.glob(f"{path.name}.partial.*")):
        raise FileExistsError(path)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and, unlike os.replace, cannot
        # overwrite a concurrently created lock.
        os.link(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    # This is the same correction/resume action lock used by the only frozen
    # queue-55-aware wrapper for indices 56..60.  Holding it across validation
    # and publication prevents q59 or another correction action from crossing
    # the post-command/pre-closeout boundary.
    with correction_runtime.action_lock():
        payload = build_lock()
        atomic_write_json_no_clobber(OUTPUT, payload)
    print(
        "P07_Q58_ORPHAN_CLOSEOUT_LOCK_V1_PASS "
        f"hash={payload['closeout_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
