#!/usr/bin/env python3
"""Assemble operational no-harm evidence without promoting pending P07 outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E3 = ROOT / "papers/e3_dualmetric_summary.csv"
JULY_CASES = ROOT / "papers/frozen_frontend_eval_20260714/analysis-output/case_summary.csv"
OUTPUT = ROOT / "papers/normal_noharm.csv"
H07_KLT = ROOT / "logs/aqualoc_real_vins/external_klt_every2_may22_mirrorinject_h07_1660_1720_klt/features.bag"
H07_PROPOSED = ROOT / "logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_h07_1660_1720_loftr/features.bag"
A02_AUDIT = ROOT / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_003_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01/audit_v2.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    e3_rows = read_csv(E3)
    e3 = {(row["case_id"], row["arm"]): row for row in e3_rows}
    july = {row["case_id"]: row for row in read_csv(JULY_CASES)}
    output: list[dict[str, object]] = []

    zero_action_cases = [
        row
        for row in july.values()
        if row["fresh_export"] == "1" and row["learned_active"] == "0"
    ]
    for source in zero_action_cases:
        full = e3[(source["case_id"], "full")]
        klt = e3[(source["case_id"], "klt")]
        output.append(
            {
                "case_id": source["case_id"],
                "dataset_family": source["dataset_family"],
                "window": source["window"],
                "texture_role": "historical_zero_action_control",
                "evidence_scope": "DEVELOPMENT_FROZEN_JULY_NOT_P07_CONFIRMATORY",
                "learned_active": 0,
                "learned_lineage_count": 0,
                "byte_identical_fallback": int(
                    source["full_bag_sha256"] == source["klt_bag_sha256"]
                ),
                "full_ape_rmse_m": full["ape_rmse_m"],
                "klt_ape_rmse_m": klt["ape_rmse_m"],
                "full_rpe_rmse_m": full["rpe_rmse_m"],
                "klt_rpe_rmse_m": klt["rpe_rmse_m"],
                "ape_valid": full["ape_valid"],
                "rpe_valid": full["rpe_valid"],
                "within_5pct_rpe": int(
                    float(full["rpe_rmse_m"]) <= 1.05 * float(klt["rpe_rmse_m"])
                ),
                "solver_risk_full": full["solver_risk"],
                "solver_risk_klt": klt["solver_risk"],
                "status": "PASS_EXACT_FRONTEND_FALLBACK",
                "source_artifact": full["g0_summary"],
                "notes": "Texture role was not outcome-blind normal selection; retain as zero-action control only.",
            }
        )

    h07_hash = sha256(H07_KLT)
    if sha256(H07_PROPOSED) != h07_hash:
        raise ValueError("H07 proposed/KLT bags are not byte-identical")
    output.append(
        {
            "case_id": "h07_1660_1720",
            "dataset_family": "aqualoc_real",
            "window": "H07_1660-1720",
            "texture_role": "known_normal_zero_action",
            "evidence_scope": "DEVELOPMENT_NORMAL",
            "learned_active": 0,
            "learned_lineage_count": 0,
            "byte_identical_fallback": 1,
            "full_ape_rmse_m": "0.050207",
            "klt_ape_rmse_m": "0.050207",
            "full_rpe_rmse_m": "0.113416",
            "klt_rpe_rmse_m": "0.113417",
            "ape_valid": 1,
            "rpe_valid": 1,
            "within_5pct_rpe": 1,
            "solver_risk_full": 0,
            "solver_risk_klt": 0,
            "status": "PASS_BYTE_IDENTICAL_NORMAL_FALLBACK",
            "source_artifact": "logs/may22_mirrorinject_vins_summary.csv",
            "notes": f"Both feature bags sha256={h07_hash}; exported learned/LoFTR observations=0.",
        }
    )

    active_case = july["mclab2_s110_d10"]
    full = e3[("mclab2_s110_d10", "full")]
    klt = e3[("mclab2_s110_d10", "klt")]
    output.append(
        {
            "case_id": "mclab2_s110_d10",
            "dataset_family": active_case["dataset_family"],
            "window": active_case["window"],
            "texture_role": "development_active_normal_profile",
            "evidence_scope": "DEVELOPMENT_ACTIVE_NORMAL_NOT_CONFIRMATORY",
            "learned_active": 1,
            "learned_lineage_count": active_case["learned_track_ids"],
            "byte_identical_fallback": 0,
            "full_ape_rmse_m": full["ape_rmse_m"],
            "klt_ape_rmse_m": klt["ape_rmse_m"],
            "full_rpe_rmse_m": full["rpe_rmse_m"],
            "klt_rpe_rmse_m": klt["rpe_rmse_m"],
            "ape_valid": full["ape_valid"],
            "rpe_valid": full["rpe_valid"],
            "within_5pct_rpe": int(
                float(full["rpe_rmse_m"]) <= 1.05 * float(klt["rpe_rmse_m"])
            ),
            "solver_risk_full": full["solver_risk"],
            "solver_risk_klt": klt["solver_risk"],
            "status": "PASS_RPE_NOHARM_ACTIVE_NORMAL_DEVELOPMENT",
            "source_artifact": full["g0_summary"],
            "notes": "APE common support is invalid; active-normal evidence is RPE-only and one development window.",
        }
    )

    a02 = json.loads(A02_AUDIT.read_text(encoding="utf-8"))
    output.append(
        {
            "case_id": "p07_a02_0005_frontend_only",
            "dataset_family": "aqualoc_archaeology",
            "window": "A02_4500-5400",
            "texture_role": "confirmatory_low_zero_action_not_normal",
            "evidence_scope": "P07_FRONTEND_ONLY_TRAJECTORY_UNREAD",
            "learned_active": 0,
            "learned_lineage_count": a02["learned_lineages"][
                "accepted_learned_born_lineage_count"
            ],
            "byte_identical_fallback": int(
                a02["zero_action_identity"]["status"] == "PASS_BYTE_IDENTICAL_TO_B1"
            ),
            "full_ape_rmse_m": "",
            "klt_ape_rmse_m": "",
            "full_rpe_rmse_m": "",
            "klt_rpe_rmse_m": "",
            "ape_valid": "",
            "rpe_valid": "",
            "within_5pct_rpe": "",
            "solver_risk_full": "",
            "solver_risk_klt": "",
            "status": "PASS_FRONTEND_FALLBACK_TRAJECTORY_PENDING",
            "source_artifact": str(A02_AUDIT.relative_to(ROOT)),
            "notes": "Included only to attest the frozen P07 zero-action contract; this is a low window and not in the normal no-harm denominator.",
        }
    )

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(f"NORMAL_NOHARM_COMPLETE rows={len(output)}")
    print(f"output={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
