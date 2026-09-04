#!/usr/bin/env python3
"""Build the current M/XFeat evidence ledger without inventing pending trajectories."""

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
FAIRNESS = ROOT / "papers/ieee_sensors_journal_experiments/p05/fairness_audit.csv"
OUTPUT = ROOT / "papers/modern_baseline_M_results.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit_path(index: int, tag: str) -> Path | None:
    attempt = (
        governance.P07 / "frontend_attempts" / f"queue_{index:03d}_{tag}"
    )
    for name in ("audit_v3.json", "audit_v2.json"):
        path = attempt / name
        if path.is_file():
            return path
    return None


def main() -> int:
    output: list[dict[str, object]] = []
    for row in read_csv(FAIRNESS):
        output.append(
            {
                "scope": "P05_DEVELOPMENT_EXPORT_PROBE",
                "case_id": row["label"],
                "queue_index": "",
                "window_id": row["label"],
                "dataset_family": row["label"].split("_", 1)[0],
                "sequence": "",
                "frontend_status": row["status"],
                "feature_frames": row["feature_frames"],
                "feature_observations": row["observation_count"],
                "feature_bag_sha256": row["bag_sha256"],
                "source_codes": row["source_codes"],
                "q_min": row["q_min"],
                "q_max": row["q_max"],
                "ape_rmse_m": "",
                "rpe_rmse_m": "",
                "ape_valid": "",
                "rpe_valid": "",
                "backend_replays_terminal": 0,
                "runtime_s": "",
                "resource_contract": "same backend/config/budget contract; export-only",
                "source_artifact": str(FAIRNESS.relative_to(ROOT)),
                "notes": "P05 fairness/integration probe; no trajectory winner claim.",
            }
        )

    allocations = {
        int(row["queue_index"]): row
        for row in governance.read_csv(governance.ALLOCATION_CSV)
    }
    for queue in governance.read_csv(governance.EXPORT_QUEUE):
        if queue["arm"] != governance.M_ARM:
            continue
        index = int(queue["queue_index"])
        allocation = allocations[index]
        chain = registry.registry_chain(allocation["run_id"])
        latest = chain[-1]
        audit_file = audit_path(index, queue["tag"])
        audit = (
            json.loads(audit_file.read_text(encoding="utf-8"))
            if audit_file is not None
            else None
        )
        bag = audit.get("feature_bag", {}) if audit else {}
        output.append(
            {
                "scope": "P07_OUTCOME_BLIND_CONFIRMATORY_MATRIX",
                "case_id": queue["window_id"],
                "queue_index": index,
                "window_id": queue["window_id"],
                "dataset_family": queue["dataset_family"],
                "sequence": queue["sequence"],
                "frontend_status": latest["status"],
                "feature_frames": bag.get("feature_frames", ""),
                "feature_observations": bag.get("feature_observations", ""),
                "feature_bag_sha256": bag.get("sha256", ""),
                "source_codes": json.dumps(bag.get("source_counts", {}), sort_keys=True),
                "q_min": bag.get("quality_min", ""),
                "q_max": bag.get("quality_max", ""),
                "ape_rmse_m": "",
                "rpe_rmse_m": "",
                "ape_valid": "",
                "rpe_valid": "",
                "backend_replays_terminal": 0,
                "runtime_s": "",
                "resource_contract": "official XFeat pairwise same-backend reproduction; native-q",
                "source_artifact": (
                    str(audit_file.relative_to(ROOT))
                    if audit_file is not None
                    else "papers/ieee_sensors_journal_experiments/p07/frontend_export_queue_v1.csv"
                ),
                "notes": (
                    "Frontend export audited; trajectory remains unread until global P07 export/D closeout."
                    if latest["status"] == "COMPLETED"
                    else "Frozen queue allocation; frontend and trajectory results pending."
                ),
            }
        )

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(f"MODERN_BASELINE_LEDGER_COMPLETE rows={len(output)}")
    print(f"output={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
