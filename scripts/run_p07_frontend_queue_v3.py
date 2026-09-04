#!/usr/bin/env python3
"""Resume the frozen P07 frontend queue serially and resolve D per triplet."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as resolver
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as resolver  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=governance.ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"queue command failed rc={completed.returncode}: {command}")


def latest_status(index: int) -> str:
    allocation = auditor.allocation_row(index)
    return registry.registry_chain(allocation["run_id"])[-1]["status"]


def window_is_terminal(window_id: str) -> bool:
    manifest = auditor.manifest_row(window_id)
    matches = resolver.matching_applicability_rows(
        governance.read_csv(resolver.APPLICABILITY), manifest
    )
    return any(row["resolution"] != "PENDING_APPLICABILITY" for row in matches)


def group_window(index: int) -> str:
    if index % 3 != 0:
        raise ValueError("triplet closeout requires an index divisible by three")
    rows = [auditor.queue_row(value) for value in range(index - 2, index + 1)]
    windows = {row["window_id"] for row in rows}
    if len(windows) != 1:
        raise ValueError(f"queue triplet is not one window: {rows}")
    return windows.pop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-index", type=int, default=7)
    parser.add_argument("--end-index", type=int, default=60)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not (7 <= args.start_index <= args.end_index <= 60):
        raise ValueError("queue range must be within generalized indices 7..60")

    for index in range(args.start_index, args.end_index + 1):
        status = latest_status(index)
        if status == "PLANNED":
            print(json.dumps({"queue_index": index, "action": "PREFLIGHT"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v3.py",
                    "--queue-index",
                    str(index),
                    "--preflight-only",
                ]
            )
            print(json.dumps({"queue_index": index, "action": "EXECUTE"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v3.py",
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
            window_id = group_window(index)
            if window_is_terminal(window_id):
                print(
                    json.dumps({"window_id": window_id, "action": "SKIP_D_TERMINAL"}),
                    flush=True,
                )
            else:
                print(json.dumps({"window_id": window_id, "action": "RESOLVE_D"}), flush=True)
                run_checked(
                    [
                        "python3",
                        "scripts/build_p07_d_resolution_lock_v2.py",
                        "--window-id",
                        window_id,
                    ]
                )
                run_checked(
                    [
                        "python3",
                        "scripts/resolve_p07_d_applicability_v2.py",
                        "--window-id",
                        window_id,
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
