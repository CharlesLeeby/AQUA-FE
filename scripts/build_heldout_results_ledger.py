#!/usr/bin/env python3
"""Materialize the corrected P07 window ledger while trajectory outcomes stay sealed."""

from __future__ import annotations

import csv
import json
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "papers/heldout_results.csv"


def audit_path(index: int, tag: str) -> Path | None:
    attempt = governance.P07 / "frontend_attempts" / f"queue_{index:03d}_{tag}"
    for name in ("audit_v3.json", "audit_v2.json"):
        path = attempt / name
        if path.is_file():
            return path
    return None


def main() -> int:
    manifest = {
        row["window_id"]: row for row in governance.read_csv(governance.MANIFEST)
    }
    split = {
        row["window_id"]: row
        for row in governance.read_csv(governance.P07 / "split_role_audit_v1.csv")
    }
    queue_by_window: dict[str, list[dict[str, str]]] = {}
    for row in governance.read_csv(governance.EXPORT_QUEUE):
        queue_by_window.setdefault(row["window_id"], []).append(row)
    applicability = governance.read_csv(governance.BUNDLE / "arm_applicability.csv")
    output: list[dict[str, object]] = []
    for window_id, selected in manifest.items():
        queue_rows = queue_by_window[window_id]
        arm_status: dict[str, str] = {}
        p_lineages: str | int = ""
        p_audit_path = ""
        for queue in queue_rows:
            index = int(queue["queue_index"])
            allocation = next(
                row
                for row in governance.read_csv(governance.ALLOCATION_CSV)
                if int(row["queue_index"]) == index
            )
            latest = registry.registry_chain(allocation["run_id"])[-1]
            arm_status[queue["arm"]] = latest["status"]
            if queue["arm"] == governance.P_ARM:
                p_lineages = latest["accepted_lineage_count"]
                path = audit_path(index, queue["tag"])
                p_audit_path = str(path.relative_to(ROOT)) if path else ""
        terminal_d = [
            row
            for row in applicability
            if row["dataset_family"] == selected["dataset_family"]
            and row["sequence"] == selected["sequence"]
            and float(row["window_start"]) == float(selected["window_start_s"])
            and float(row["window_end"]) == float(selected["window_end_s"])
            and row["resolution"] != "PENDING_APPLICABILITY"
        ]
        d_resolution = terminal_d[-1]["resolution"] if terminal_d else "PENDING_APPLICABILITY"
        all_exports = all(status == "COMPLETED" for status in arm_status.values())
        output.append(
            {
                "window_id": window_id,
                "dataset_family": selected["dataset_family"],
                "data_domain": selected["data_domain"],
                "sequence": selected["sequence"],
                "window_start_s": selected["window_start_s"],
                "window_end_s": selected["window_end_s"],
                "texture_stratum": selected["texture_stratum"],
                "selection_tier": selected["selection_tier"],
                "heldout_class": split[window_id]["corrected_split_role"],
                "external_held_out": split[window_id]["external_held_out"],
                "b1_frontend_status": arm_status.get(governance.B1, ""),
                "p_frontend_status": arm_status.get(governance.P_ARM, ""),
                "m_frontend_status": arm_status.get(governance.M_ARM, ""),
                "p_accepted_lineage_count": p_lineages,
                "d_resolution": d_resolution,
                "frontend_triplet_terminal": int(all_exports and d_resolution != "PENDING_APPLICABILITY"),
                "backend_queue_frozen": 0,
                "backend_replays_terminal": 0,
                "ape_rmse_m": "",
                "rpe_rmse_m": "",
                "ape_valid": "",
                "rpe_valid": "",
                "trajectory_outcome_read": 0,
                "p_frontend_audit": p_audit_path,
                "status": (
                    "FRONTEND_TERMINAL_TRAJECTORY_SEALED"
                    if all_exports and d_resolution != "PENDING_APPLICABILITY"
                    else "P07_FRONTEND_IN_PROGRESS"
                ),
                "reporting_boundary": split[window_id]["reporting_claim"],
            }
        )
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(
        "HELDOUT_LEDGER_COMPLETE "
        f"windows={len(output)} frontend_terminal={sum(row['frontend_triplet_terminal'] for row in output)}"
    )
    print(f"output={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
