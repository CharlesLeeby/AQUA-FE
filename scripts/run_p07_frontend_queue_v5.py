#!/usr/bin/env python3
"""Resume the P07 queue under the v5 AFRL-aware execution adapter."""

from __future__ import annotations

import argparse
import json
import subprocess

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as resolver
    from scripts import run_p07_frontend_queue_v3 as v3_queue
    from scripts import run_p07_frontend_queue_v4 as v4_queue
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as resolver  # type: ignore
    import run_p07_frontend_queue_v3 as v3_queue  # type: ignore
    import run_p07_frontend_queue_v4 as v4_queue  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=governance.ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"queue command failed rc={completed.returncode}: {command}")


def latest_status(index: int) -> str:
    allocation = auditor.allocation_row(index)
    return registry.registry_chain(allocation["run_id"])[-1]["status"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-index", type=int, default=29)
    parser.add_argument("--end-index", type=int, default=60)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not (29 <= args.start_index <= args.end_index <= 60):
        raise ValueError("queue range must be within v5 indices 29..60")
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
                print(json.dumps({"window_id": window_id, "action": "RESOLVE_D"}), flush=True)
                lock_path = resolver.resolution_lock_path(window_id)
                if not lock_path.is_file():
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
