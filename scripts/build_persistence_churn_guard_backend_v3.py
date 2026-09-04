#!/usr/bin/env python3
"""Build exact-input backend reuse tables for churn-guard v3."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_churn_guard_v3"
V1_PAPER = ROOT / "papers/frontend_persistence_conditioned_replacement_v1"
RUNTIME = ROOT / "artifacts/frontend_persistence_churn_guard_v3"
WINDOWS = (
    "a06_s000_d045",
    "a09_6000_6800",
    "a06_s045_d045",
    "h07_s000_d050",
)
SOURCE_ARM = {
    "a06_s000_d045": "klt",
    "a09_6000_6800": "persistence_replace",
    "a06_s045_d045": "persistence_replace",
    "h07_s000_d050": "klt",
}
FAMILY = {
    "a06_s000_d045": "aqualoc_archaeo_vins",
    "a09_6000_6800": "aqualoc_archaeo_vins",
    "a06_s045_d045": "aqualoc_archaeo_vins",
    "h07_s000_d050": "aqualoc_real_vins",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def v3_bag(window: str) -> Path:
    return RUNTIME / "shadow_root/logs" / FAMILY[window] / (
        f"external_hybrid_xfeat_every2_pcgv3_{window}/features.bag"
    )


def select_one(
    rows: list[dict[str, str]],
    *,
    window: str,
    arm: str,
    repeat: str | None = None,
) -> dict[str, str]:
    selected = [
        row for row in rows
        if row.get("window") == window
        and row.get("arm") == arm
        and (repeat is None or row.get("repeat") == repeat)
    ]
    if len(selected) != 1:
        raise RuntimeError(f"expected one row for {window}/{arm}/{repeat}: {len(selected)}")
    return dict(selected[0])


def main() -> int:
    validation = read_csv(PAPER / "frontend_validation.csv")
    if len(validation) != 4 or any(row["status"] != "PASS" for row in validation):
        raise RuntimeError("frontend validation is not 4/4 PASS")
    validated_hash = {row["window"]: row["feature_bag_sha256"] for row in validation}
    for window in WINDOWS:
        if sha256(v3_bag(window)) != validated_hash[window]:
            raise RuntimeError(f"v3 bag changed after validation: {window}")

    source_accuracy = read_csv(V1_PAPER / "accuracy.csv")
    source_repeats = read_csv(V1_PAPER / "accuracy_repeats.csv")
    source_runability = read_csv(V1_PAPER / "runability.csv")
    source_audit = read_csv(V1_PAPER / "backend_config_audit.csv")

    accuracy: list[dict[str, object]] = []
    repeats: list[dict[str, object]] = []
    runability: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []

    for window in WINDOWS:
        source_arm = SOURCE_ARM[window]
        for output_arm, result_arm in (("klt", "klt"), ("churn_guard_v3", source_arm)):
            row = select_one(source_accuracy, window=window, arm=result_arm)
            row["arm"] = output_arm
            row["result_provenance"] = f"exact_input_reuse:{result_arm}"
            row["feature_bag_sha256"] = (
                validated_hash[window]
                if output_arm == "churn_guard_v3"
                else select_one(source_audit, window=window, arm="klt", repeat="1")[
                    "feature_bag_sha256"
                ]
            )
            accuracy.append(row)

            run_row = select_one(source_runability, window=window, arm=result_arm)
            run_row["arm"] = output_arm
            run_row["reuse_exact_input"] = True
            run_row["source_result_arm"] = result_arm
            runability.append(run_row)

            for repeat in ("1", "2", "3"):
                repeat_row = select_one(
                    source_repeats,
                    window=window,
                    arm=result_arm,
                    repeat=repeat,
                )
                repeat_row["arm"] = output_arm
                repeat_row["result_provenance"] = f"exact_input_reuse:{result_arm}"
                repeats.append(repeat_row)

                audit_row = select_one(
                    source_audit,
                    window=window,
                    arm=result_arm,
                    repeat=repeat,
                )
                audit_row["arm"] = output_arm
                audit_row["status"] = f"EXACT_INPUT_REUSE_FROM_{result_arm.upper()}"
                audit_row["source_result_arm"] = result_arm
                if output_arm == "churn_guard_v3":
                    audit_row["feature_bag"] = str(v3_bag(window))
                    audit_row["feature_bag_sha256"] = validated_hash[window]
                audit.append(audit_row)

        klt = select_one(source_accuracy, window=window, arm="klt")
        guarded = select_one(source_accuracy, window=window, arm=source_arm)
        klt_ape = float(klt["fixed_se3_ape_rmse_median_m"])
        guarded_ape = float(guarded["fixed_se3_ape_rmse_median_m"])
        klt_rpe = float(klt["fixed_se3_rpe_rmse_median_m"])
        guarded_rpe = float(guarded["fixed_se3_rpe_rmse_median_m"])
        decision = {
            "a06_s000_d045": "REPAIR_PASS_EXACT_KLT",
            "a09_6000_6800": "POSITIVE_RETAINED_EXACT_V1",
            "a06_s045_d045": "POSITIVE_RETAINED_EXACT_V1",
            "h07_s000_d050": "NO_HARM_EXACT_KLT",
        }[window]
        decisions.append(
            {
                "window": window,
                "decision": decision,
                "source_result_arm": source_arm,
                "fixed_se3_ape_change_percent_vs_klt": 100.0 * (guarded_ape / klt_ape - 1.0),
                "fixed_se3_rpe_change_percent_vs_klt": 100.0 * (guarded_rpe / klt_rpe - 1.0),
                "v3_feature_bag_sha256": validated_hash[window],
            }
        )

    # Every v3 row must use the same normalized backend config and binaries as
    # the paired KLT row for the same window/repeat.
    for window in WINDOWS:
        for repeat in ("1", "2", "3"):
            klt = next(
                row for row in audit
                if row["window"] == window and row["arm"] == "klt" and row["repeat"] == repeat
            )
            guarded = next(
                row for row in audit
                if row["window"] == window
                and row["arm"] == "churn_guard_v3"
                and row["repeat"] == repeat
            )
            for key in (
                "normalized_backend_config_sha256",
                "vins_node_sha256",
                "libvins_sha256",
            ):
                if klt[key] != guarded[key]:
                    raise RuntimeError(f"backend mismatch {window}/{repeat}/{key}")

    write_csv(PAPER / "accuracy.csv", accuracy)
    write_csv(PAPER / "accuracy_repeats.csv", repeats)
    write_csv(PAPER / "runability.csv", runability)
    write_csv(PAPER / "backend_config_audit.csv", audit)
    write_csv(PAPER / "decisions.csv", decisions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
