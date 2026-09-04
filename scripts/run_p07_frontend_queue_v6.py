#!/usr/bin/env python3
"""Resume P07 with v5 frontend audits and v3 D-resolution compatibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v3 as resolver
    from scripts import run_p07_frontend_queue_v3 as v3_queue
    from scripts import run_p07_frontend_queue_v4 as v4_queue
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v3 as resolver  # type: ignore
    import run_p07_frontend_queue_v3 as v3_queue  # type: ignore
    import run_p07_frontend_queue_v4 as v4_queue  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


LOCK_PATH = governance.P07 / "frontend_orchestration_correction_lock_v6.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("orchestration_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_lock(start_index: int, end_index: int) -> dict[str, object]:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version")
        != "isj-p07-frontend-orchestration-correction-lock-v6"
        or payload.get("status")
        != "FROZEN_READY_WITH_V4_AUDIT_AND_V3_D_RESOLUTION"
        or payload.get("orchestration_lock_hash") != lock_hash(payload)
    ):
        raise RuntimeError("v6 orchestration lock schema, status, or hash mismatch")
    allowed = set(int(value) for value in payload["allowed_queue_indices"])
    if not set(range(start_index, end_index + 1)).issubset(allowed):
        raise RuntimeError("requested queue range is outside the v6 lock")
    for record in payload["artifacts"]:
        path = governance.ROOT / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise RuntimeError(f"v6 locked artifact drift: {path}")
    for snapshot in payload["mutable_stream_prefix_snapshots"]:
        path = governance.ROOT / snapshot["path"]
        content = path.read_bytes()
        size = int(snapshot["size_bytes"])
        if len(content) < size or hashlib.sha256(content[:size]).hexdigest() != snapshot["sha256"]:
            raise RuntimeError(f"v6 append-only stream prefix drift: {path}")
    return payload


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=governance.ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"queue command failed rc={completed.returncode}: {command}")


def latest_status(index: int) -> str:
    allocation = auditor.allocation_row(index)
    return registry.registry_chain(allocation["run_id"])[-1]["status"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-index", type=int, default=31)
    parser.add_argument("--end-index", type=int, default=60)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not (31 <= args.start_index <= args.end_index <= 60):
        raise ValueError("queue range must be within v6 indices 31..60")
    validate_lock(args.start_index, args.end_index)
    v4_queue.require_previous_triplet_closeout(args.start_index)

    for index in range(args.start_index, args.end_index + 1):
        status = latest_status(index)
        if status == "PLANNED":
            print(json.dumps({"queue_index": index, "action": "PREFLIGHT"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v5.py",
                    "--queue-index",
                    str(index),
                    "--preflight-only",
                ]
            )
            print(json.dumps({"queue_index": index, "action": "EXECUTE"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v5.py",
                    "--queue-index",
                    str(index),
                    "--timeout-s",
                    str(args.timeout_s),
                ]
            )
        elif status != "COMPLETED":
            raise RuntimeError(
                f"queue index {index} latest status {status}; replacement governance required"
            )
        else:
            print(json.dumps({"queue_index": index, "action": "SKIP_COMPLETED"}), flush=True)

        if index % 3 == 0:
            window_id = v3_queue.group_window(index)
            if v4_queue.window_is_terminal_complete(window_id):
                print(
                    json.dumps({"window_id": window_id, "action": "SKIP_D_TERMINAL"}),
                    flush=True,
                )
            else:
                print(json.dumps({"window_id": window_id, "action": "RESOLVE_D_V3"}), flush=True)
                lock_path = resolver.resolution_lock_path(window_id)
                if not lock_path.is_file():
                    run_checked(
                        [
                            "python3",
                            "scripts/build_p07_d_resolution_lock_v3.py",
                            "--window-id",
                            window_id,
                        ]
                    )
                run_checked(
                    [
                        "python3",
                        "scripts/resolve_p07_d_applicability_v3.py",
                        "--window-id",
                        window_id,
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
