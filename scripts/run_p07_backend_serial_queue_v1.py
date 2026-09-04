#!/usr/bin/env python3
"""Preview or serially advance the frozen P07 backend replay queue.

The default is read-only preview.  ``--execute`` still invokes only the frozen
job entrypoint, one process at a time, and stops at the first WAITING,
infrastructure/replacement, orphan-reconcile, or fail-closed condition.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import allocate_p07_backend_replacement_v1 as replacement_allocator
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import run_p07_backend_replay_job_v1 as job
except ModuleNotFoundError:
    import allocate_p07_backend_replacement_v1 as replacement_allocator  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import run_p07_backend_replay_job_v1 as job  # type: ignore


SCHEMA = "isj-p07-backend-serial-queue-controller-v1"
JOB_ENTRYPOINT = "scripts/run_p07_backend_replay_job_v1.py"
REPLACEMENT_INDEX = (
    common.P07 / "backend_replacement_allocation_v1.csv"
)


class ControllerViolation(common.BackendReplayViolation):
    """The serial controller cannot safely select the next queue action."""


def _replacement_for_index(
    root: Path, queue_index: int, base_row: Mapping[str, str]
) -> tuple[dict[str, str], str | None]:
    try:
        rows = replacement_allocator.read_index(
            root / common.display_path(common.ROOT, REPLACEMENT_INDEX)
        )
    except replacement_allocator.ReplacementAllocationError as error:
        raise ControllerViolation(f"replacement index drift: {error}") from error
    relevant = [row for row in rows if int(row["queue_index"]) == queue_index]
    base_run_id = base_row["run_id"]
    parent = base_run_id
    effective_row = dict(base_row)
    lock_relative: str | None = None
    for attempt, item in enumerate(relevant, 2):
        if (
            int(item["attempt_number"]) != attempt
            or item["root_queue_run_id"] != base_run_id
            or item["failed_run_id"] != parent
            or item["replacement_for"] != parent
        ):
            raise ControllerViolation(
                f"replacement allocation chain drift at queue {queue_index}"
            )
        lock_path, lock_content, _lock_identity = (
            common.read_direct_workspace_bytes(
                root,
                item["replacement_lock_path"],
                label="controller replacement lock",
            )
        )
        if common.sha256_bytes(lock_content) != item["replacement_lock_sha256"]:
            raise ControllerViolation("controller replacement-lock SHA drift")
        try:
            payload = json.loads(lock_content)
            replacement_allocator.validate_replacement_lock_payload(
                payload, expected_relative_path=item["replacement_lock_path"]
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            replacement_allocator.ReplacementAllocationError,
        ) as error:
            raise ControllerViolation("controller replacement lock is invalid") from error
        effective_row = payload.get("effective_queue_row")
        if (
            not isinstance(effective_row, dict)
            or payload.get("base_queue_row") != dict(base_row)
            or payload.get("attempt_number") != attempt
            or payload.get("failed_run_id") != parent
            or payload.get("replacement_for") != parent
            or effective_row.get("run_id") != item["run_id"]
        ):
            raise ControllerViolation("controller replacement effective row drift")
        parent = item["run_id"]
        effective_row = {key: str(value) for key, value in effective_row.items()}
        lock_relative = item["replacement_lock_path"]
    return effective_row, lock_relative


def plan_next_action(
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
    registry_path: Path,
    start_index: int,
    end_index: int | None,
) -> dict[str, Any]:
    lock = common.validate_execution_lock(
        root,
        execution_lock_path,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    order = job._execution_order(lock)
    stop = len(order) if end_index is None else end_index
    if start_index < 1 or stop < start_index or stop > len(order):
        raise ControllerViolation("invalid serial controller start/end range")
    for queue_index in order:
        if queue_index < start_index or queue_index > stop:
            continue
        base = common.indexed_row(queue_path, queue_index)
        effective_row, replacement_lock = _replacement_for_index(
            root, queue_index, base
        )
        effective_run_id = effective_row["run_id"]
        chain = job.registry_chain(registry_path, effective_run_id)
        latest = chain[-1]
        disposition = job.terminal_slot_disposition(
            root=root, row=effective_row, latest=latest
        )
        if disposition in {"COMPLETED", "ALGORITHM_HARD_FAILURE"}:
            continue
        intent_token = common.sha256_bytes(effective_run_id.encode("utf-8"))[:20]
        effective_intent = (
            root
            / job.ATTEMPT_INTENT_ROOT_RELATIVE
            / (
                f"queue_{queue_index:03d}_{intent_token}_"
                "attempt_intent_v1.json"
            )
        )
        has_effective_intent = os.path.lexists(effective_intent)
        if latest["status"] == "RUNNING" or has_effective_intent:
            return {
                "schema_version": SCHEMA,
                "status": "STOP_RECONCILE_REQUIRED",
                "queue_index": queue_index,
                "run_id": effective_run_id,
                "replacement_lock": replacement_lock,
                "registry_status": latest["status"],
                "attempt_intents": (
                    [common.display_path(root, effective_intent)]
                    if has_effective_intent
                    else []
                ),
                "parallel_execution": False,
            }
        if disposition == "INFRASTRUCTURE_FAILURE":
            return {
                "schema_version": SCHEMA,
                "status": "STOP_REPLACEMENT_REQUIRED",
                "queue_index": queue_index,
                "run_id": effective_run_id,
                "replacement_lock": replacement_lock,
                "registry_status": latest["status"],
                "parallel_execution": False,
            }
        if latest["status"] != "PLANNED":
            raise ControllerViolation(
                f"unsupported effective registry state at queue {queue_index}: {latest['status']}"
            )
        argv = [
            "python3",
            JOB_ENTRYPOINT,
            "--queue-index",
            str(queue_index),
            "--execution-lock",
            common.DEFAULT_EXECUTION_LOCK_RELATIVE,
        ]
        if replacement_lock is not None:
            argv.extend(["--replacement-lock", replacement_lock])
        return {
            "schema_version": SCHEMA,
            "status": "READY_NEXT_JOB",
            "queue_index": queue_index,
            "run_id": effective_run_id,
            "replacement_lock": replacement_lock,
            "registry_status": latest["status"],
            "job_argv": argv,
            "execution_lock_path": common.display_path(root, execution_lock_path),
            "execution_lock_sha256": common.sha256(execution_lock_path),
            "queue_path": common.display_path(root, queue_path),
            "allocation_path": common.display_path(root, allocation_path),
            "parallel_execution": False,
        }
    return {
        "schema_version": SCHEMA,
        "status": "RANGE_TERMINAL",
        "start_index": start_index,
        "end_index": stop,
        "parallel_execution": False,
    }


def run_one(action: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    if action.get("status") != "READY_NEXT_JOB" or not isinstance(
        action.get("job_argv"), list
    ):
        raise ControllerViolation("serial execution requires one READY_NEXT_JOB action")
    base_argv = [str(item) for item in action["job_argv"]]
    if len(base_argv) < 2 or base_argv[:2] != ["python3", JOB_ENTRYPOINT]:
        raise ControllerViolation("serial action job argv is not the frozen entrypoint")
    lock_relative = str(
        action.get("execution_lock_path", common.DEFAULT_EXECUTION_LOCK_RELATIVE)
    )
    queue_relative = str(action.get("queue_path", common.display_path(common.ROOT, common.DEFAULT_QUEUE)))
    allocation_relative = str(
        action.get("allocation_path", common.display_path(common.ROOT, common.DEFAULT_ALLOCATION))
    )
    lock_path = common.workspace_path(root, lock_relative, label="controller execution lock")
    queue_path = common.workspace_path(root, queue_relative, label="controller backend queue")
    allocation_path = common.workspace_path(
        root, allocation_relative, label="controller backend allocation"
    )
    lock = common.validate_execution_lock(
        root,
        lock_path,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    lock_sha256 = common.sha256(lock_path)
    expected_lock_hash = action.get("execution_lock_sha256")
    if expected_lock_hash is not None and expected_lock_hash != lock_sha256:
        raise ControllerViolation("serial action execution-lock SHA drift")
    with common.SealedRuntimeBundle(
        root, lock, execution_lock_sha256=lock_sha256
    ) as runtime:
        environment = common.sealed_runtime_environment(runtime)
        sealed_base_argv = runtime.python_argv("job_entrypoint", base_argv[2:])
        preflight = subprocess.run(
            [*sealed_base_argv, "--preflight-only"],
            cwd=root,
            env=environment,
            pass_fds=runtime.pass_fds,
            text=True,
            capture_output=True,
            check=False,
        )
        if preflight.returncode != 0:
            return {
                **dict(action),
                "status": "STOP_PREFLIGHT_WAITING" if preflight.returncode == 75 else "STOP_PREFLIGHT_FAILED",
                "returncode": preflight.returncode,
                "stdout": preflight.stdout,
                "stderr": preflight.stderr,
            }
        completed = subprocess.run(
            sealed_base_argv,
            cwd=root,
            env=environment,
            pass_fds=runtime.pass_fds,
            text=True,
            capture_output=True,
            check=False,
        )
    return {
        **dict(action),
        "status": "JOB_COMPLETED" if completed.returncode == 0 else (
            "STOP_JOB_WAITING" if completed.returncode == 75 else "STOP_JOB_FAILED"
        ),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--end-index", type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        action = plan_next_action(
            root=common.ROOT,
            queue_path=common.DEFAULT_QUEUE,
            allocation_path=common.DEFAULT_ALLOCATION,
            execution_lock_path=common.DEFAULT_EXECUTION_LOCK,
            registry_path=common.DEFAULT_REGISTRY,
            start_index=args.start_index,
            end_index=args.end_index,
        )
        if not args.execute:
            print(json.dumps({**action, "mode": "PREVIEW"}, indent=2, sort_keys=True))
            return 0 if action["status"] in {"READY_NEXT_JOB", "RANGE_TERMINAL"} else 75
        result = run_one(action, root=common.ROOT)
        print(json.dumps({**result, "mode": "EXECUTE_ONE"}, indent=2, sort_keys=True))
        return 0 if result["status"] == "JOB_COMPLETED" else 75
    except (common.BackendReplayViolation, OSError) as error:
        print(f"P07_BACKEND_SERIAL_FAIL_CLOSED: {error}", file=os.sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
