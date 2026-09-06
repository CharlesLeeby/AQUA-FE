#!/usr/bin/env python3
"""Admit EXP-20260906-009 to backend only after matched controls pass."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    decision_path = PAPER / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("decision") != "PENDING_MATCHED_CONTROL":
        raise RuntimeError(
            "frontend must be PENDING_MATCHED_CONTROL before final admission"
        )
    plan_path = PAPER / "matched_control_plan.json"
    lock_path = PAPER / "matched_control_plan.lock.json"
    audit_path = PAPER / "matched_control_audit.csv"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    audit = read_csv(audit_path)
    expected_cells = int(decision["active_arm_windows"])
    if sha256(plan_path) != lock["matched_control_plan_sha256"]:
        raise RuntimeError("matched-control plan identity drift")
    if len(plan["cells"]) != expected_cells or len(audit) != expected_cells:
        raise RuntimeError("matched-control cell count mismatch")
    if any(row.get("status") != "PASS" for row in audit):
        raise RuntimeError("one or more matched controls failed structural audit")
    planned = {
        (str(cell["run_slug"]), str(cell["arm"]))
        for cell in plan["cells"]
    }
    audited = {(row["run_slug"], row["arm"]) for row in audit}
    if planned != audited:
        raise RuntimeError("matched-control plan/audit identity mismatch")

    decision["matched_control_complete"] = True
    decision["matched_control_cells"] = len(audit)
    decision["matched_control_plan_sha256"] = sha256(plan_path)
    decision["matched_control_audit_sha256"] = sha256(audit_path)
    decision["decision"] = "FRONTEND_GO"
    decision_path.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "decision": "FRONTEND_GO",
                "active_cells": expected_cells,
                "matched_audits_pass": len(audit),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
