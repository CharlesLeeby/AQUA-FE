#!/usr/bin/env python3
"""Run the frozen B0 v1 materializer through the adopted action transaction.

This wrapper grants only B0 input preparation.  It never authorizes backend
replay, G0, ROS execution, VINS, APE, or RPE.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

try:
    from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as bridge
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import run_p07_backend_b0_materialization_v1 as frozen_runtime
except ModuleNotFoundError:
    import build_p07_backend_b0_formalization_adoption_bridge_v1 as bridge  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import run_p07_backend_b0_materialization_v1 as frozen_runtime  # type: ignore


def _relative(path: Path) -> str:
    return path.relative_to(bridge.ROOT).as_posix()


def preflight(*, root: Path = bridge.ROOT) -> dict[str, object]:
    """Read-only gate; an existing action/output requires explicit review."""

    root = root.absolute()
    prelock, _record = bridge.load_prelock(root=root)
    paths = {
        "action_intent": _relative(bridge.ACTION_INTENT),
        "v1_intent": _relative(bridge.b0_plan.INTENT),
        "v1_receipt": _relative(bridge.b0_plan.RECEIPT),
        "v1_final": _relative(bridge.b0_plan.FINAL_OUTPUT),
        "closeout": _relative(bridge.CLOSEOUT),
    }
    states = {
        role: formal_io.destination_exists(root, relative)
        for role, relative in paths.items()
    }
    if any(states.values()):
        return {
            "status": "BLOCKED_EXISTING_ACTION_OR_B0_OUTPUT_REQUIRES_GOVERNED_REVIEW",
            "formal_presence": states,
            bridge.PRELOCK_HASH: prelock[bridge.PRELOCK_HASH],
            "backend_replay_authorized": False,
        }
    # The frozen preflight is read-only and is reached only while every bridge
    # and v1 action/output destination is still absent.
    payload = frozen_runtime.preflight(root=root)
    return {
        **payload,
        "b0_adoption_prelock_validated": True,
        "action_intent_required_before_frozen_execute": True,
        "backend_replay_authorized": False,
    }


def execute(
    *,
    action_started_at: str,
    completed_at: str,
    closed_at: str,
    timeout_s: int,
    action_argv: Sequence[str],
    root: Path = bridge.ROOT,
    frozen_execute: Callable[..., Mapping[str, object]] = frozen_runtime.execute,
    _after_action_test_hook: Callable[[], None] | None = None,
    _after_frozen_execute_test_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Publish action first, invoke frozen v1 under both locks, then close out."""

    root = root.absolute()
    expected_argv = bridge.canonical_wrapper_argv(
        action_started_at=action_started_at,
        completed_at=completed_at,
        closed_at=closed_at,
        timeout_s=timeout_s,
    )
    if list(action_argv) != expected_argv:
        raise bridge.B0AdoptionBridgeError("observed wrapper argv is not exact/canonical")
    with bridge.governance_locks():
        # This live load repeats every prelock absence/process check under both
        # mutexes.  A late direct invocation of the frozen runner is terminal.
        bridge.load_prelock(root=root, require_preaction_absence=True)
        action = bridge.build_live_action_intent(
            recorded_at=action_started_at,
            completed_at=completed_at,
            closed_at=closed_at,
            timeout_s=timeout_s,
            wrapper_argv=action_argv,
            root=root,
        )
        bridge.publish_action_intent_locked(action, root=root)
        published_action, _record = bridge.load_action_intent(root=root)
        if published_action != action:
            raise bridge.B0AdoptionBridgeError("published B0 action intent differs")
        bridge.wait_past_action_filesystem_time(root=root)
        if _after_action_test_hook is not None:
            _after_action_test_hook()
        # The frozen runtime takes these same two flocks internally in the
        # opposite layers.  Reuse the already-held descriptors to avoid both
        # self-deadlock and a direct-runner gap between action and mutation.
        with bridge.reuse_held_locks_for_frozen_runtime():
            frozen_execute(completed_at=completed_at, timeout_s=timeout_s, root=root)
        if _after_frozen_execute_test_hook is not None:
            _after_frozen_execute_test_hook()
        closeout = bridge.build_live_closeout(closed_at=closed_at, root=root)
        bridge.publish_closeout_locked(closeout, root=root)
        published_closeout, _record = bridge.load_closeout(root=root)
        if published_closeout != closeout:
            raise bridge.B0AdoptionBridgeError("published B0 closeout differs")
        return published_closeout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--action-started-at")
    parser.add_argument("--completed-at")
    parser.add_argument("--closed-at")
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(preflight(), indent=2, sort_keys=True))
        return 0
    if not args.action_started_at or not args.completed_at or not args.closed_at:
        parser.error(
            "--action-started-at, --completed-at and --closed-at are required with --execute"
        )
    expected = bridge.canonical_wrapper_argv(
        action_started_at=args.action_started_at,
        completed_at=args.completed_at,
        closed_at=args.closed_at,
        timeout_s=args.timeout_s,
    )
    observed = [Path(sys.executable).name, sys.argv[0], *sys.argv[1:]]
    if observed != expected:
        raise bridge.B0AdoptionBridgeError(
            f"CLI argv is not exact; expected={expected!r} observed={observed!r}"
        )
    closeout = execute(
        action_started_at=args.action_started_at,
        completed_at=args.completed_at,
        closed_at=args.closed_at,
        timeout_s=args.timeout_s,
        action_argv=observed,
    )
    print(f"P07_B0_ADOPTION_CLOSEOUT_FROZEN hash={closeout[bridge.CLOSEOUT_HASH]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
