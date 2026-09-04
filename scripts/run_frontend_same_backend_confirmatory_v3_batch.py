#!/usr/bin/env python3
"""Serial, failure-accounting batch wrapper for confirmatory-v3 frontends."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_confirmatory_v3 as runner


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_same_backend_confirmatory_v3"
)
STATUS = RUNTIME / "frontend_batch_status.json"
ANALYZER = ROOT / "scripts/analyze_frontend_same_backend_confirmatory_v3.py"


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", action="append", help="run slug; repeatable")
    args = parser.parse_args()
    runner.verify_lock()
    runner.prepare_shadow()
    windows = runner.load_windows()
    if args.window:
        requested = set(args.window)
        windows = [window for window in windows if window["run_slug"] in requested]
        missing = requested - {window["run_slug"] for window in windows}
        if missing:
            raise SystemExit(f"unknown windows: {sorted(missing)}")
    arms = runner.load_arms()
    cells = [(window["run_slug"], arm) for window in windows for arm in arms]
    payload: dict = {
        "schema_version": "aqua-fe-confirmatory-v3-frontend-batch-v1",
        "started_at": now(),
        "updated_at": now(),
        "state": "RUNNING",
        "planned_cells": len(cells),
        "completed_invocations": 0,
        "failed_invocations": [],
        "current": None,
    }
    atomic_json(STATUS, payload)
    for index, (run_slug, arm) in enumerate(cells, start=1):
        payload["current"] = {"index": index, "run_slug": run_slug, "arm": arm}
        payload["updated_at"] = now()
        atomic_json(STATUS, payload)
        command = [
            sys.executable,
            str(ROOT / "scripts/run_frontend_same_backend_confirmatory_v3.py"),
            "--window",
            run_slug,
            "--arm",
            arm,
        ]
        print(f"batch cell {index}/{len(cells)} {run_slug} {arm}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        payload["completed_invocations"] = index
        if result.returncode != 0:
            payload["failed_invocations"].append(
                {"run_slug": run_slug, "arm": arm, "return_code": result.returncode}
            )
        payload["updated_at"] = now()
        atomic_json(STATUS, payload)
        # Refresh the full 36-cell ledger after every cell, including failures.
        subprocess.run([sys.executable, str(ANALYZER)], cwd=ROOT, check=True)
    payload["current"] = None
    payload["state"] = "COMPLETE"
    payload["completed_at"] = now()
    payload["updated_at"] = now()
    atomic_json(STATUS, payload)
    print(
        f"frontend batch complete failures={len(payload['failed_invocations'])}",
        flush=True,
    )
    return 1 if payload["failed_invocations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
