#!/usr/bin/env python3
"""Resume the P07 queue under the corrected v4 execution adapter."""

from __future__ import annotations

import argparse
import json
import subprocess

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as resolver
    from scripts import run_p07_frontend_queue_v3 as v3_queue
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as resolver  # type: ignore
    import run_p07_frontend_queue_v3 as v3_queue  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=governance.ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"queue command failed rc={completed.returncode}: {command}")


def latest_status(index: int) -> str:
    allocation = auditor.allocation_row(index)
    return registry.registry_chain(allocation["run_id"])[-1]["status"]


def window_is_terminal_complete(window_id: str) -> bool:
    manifest = auditor.manifest_row(window_id)
    matches = resolver.matching_applicability_rows(
        governance.read_csv(resolver.APPLICABILITY), manifest
    )
    terminal = [row for row in matches if row["resolution"] != "PENDING_APPLICABILITY"]
    if not terminal:
        return False
    if len(terminal) != 1:
        raise RuntimeError(f"window has multiple terminal D rows: {window_id}")
    evidence = governance.ROOT / terminal[0]["evidence_path"]
    if not evidence.is_file():
        raise RuntimeError(
            f"terminal D row lacks its atomic closeout evidence: {window_id}: {evidence}"
        )
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    expected = f"PASS_{terminal[0]['resolution']}"
    current_closeout = (
        payload.get("window_id") == window_id and payload.get("status") == expected
    )
    legacy_zero_action_evidence = (
        terminal[0]["resolution"] == "NOT_APPLICABLE"
        and payload.get("window_id") == window_id
        and payload.get("status") == "PASS"
        and int(
            payload.get("learned_lineages", {}).get(
                "accepted_learned_born_lineage_count", -1
            )
        )
        == 0
        and payload.get("zero_action_identity", {}).get("status")
        == "PASS_BYTE_IDENTICAL_TO_B1"
    )
    if not current_closeout and not legacy_zero_action_evidence:
        raise RuntimeError(f"terminal D closeout identity/status mismatch: {window_id}")
    return True


def require_previous_triplet_closeout(start_index: int) -> None:
    if start_index <= 7 or start_index % 3 != 1:
        return
    previous_window = v3_queue.group_window(start_index - 1)
    if not window_is_terminal_complete(previous_window):
        raise RuntimeError(
            f"cannot resume at {start_index} before previous D closeout: {previous_window}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-index", type=int, default=7)
    parser.add_argument("--end-index", type=int, default=60)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not (7 <= args.start_index <= args.end_index <= 60):
        raise ValueError("queue range must be within corrected indices 7..60")
    require_previous_triplet_closeout(args.start_index)

    for index in range(args.start_index, args.end_index + 1):
        status = latest_status(index)
        if status == "PLANNED":
            print(json.dumps({"queue_index": index, "action": "PREFLIGHT"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v4.py",
                    "--queue-index",
                    str(index),
                    "--preflight-only",
                ]
            )
            print(json.dumps({"queue_index": index, "action": "EXECUTE"}), flush=True)
            run_checked(
                [
                    "python3",
                    "scripts/run_p07_frontend_export_job_v4.py",
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
            if window_is_terminal_complete(window_id):
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
