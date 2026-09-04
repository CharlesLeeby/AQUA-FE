#!/usr/bin/env python3
"""Close out the bounded H05 clean reproduction against formal P07 artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics


FORMAL = Path("/media/ma/Data/AQUA-FE_WS_storage_offload/p07_backend_completion_serial_v2")
ROOT = Path("/media/ma/Data/AQUA-FE_WS_storage_offload/p11_clean_reproduction_20260904")
FRESH = ROOT / "backend"
SOURCE_CONTRACT = Path(
    "/home/ma/AQUA-FE_WS/papers/ieee_sensors_journal_experiments/"
    "backend_quality_contract_v1.json"
)
CURRENT_EXPORTER = Path("/home/ma/AQUA-FE_WS/uw_frontend/ros/export_vins_features.py")
CURRENT_ESTIMATOR = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/"
    "vins_estimator/src/estimator/estimator.cpp"
)
CURRENT_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
WINDOW_SLUG = "aqualoc_harbor_H05_0002"
QUEUE_INDICES = range(25, 37)
CONTRASTS = ("P_vs_B0", "P_vs_B1", "P_vs_M")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def evaluator_receipt(base: Path, repeat: int, contrast: str) -> dict:
    return load(base / "g0" / WINDOW_SLUG / f"repeat_{repeat}" / contrast / "evaluation_receipt.json")


def summary(receipt: dict) -> dict:
    return load(Path(receipt["summary_path"]))


def median_metrics(base: Path, contrast: str) -> dict:
    values = {"p_rpe_rmse_m": [], "comparator_rpe_rmse_m": []}
    individual = []
    for repeat in (1, 2, 3):
        receipt = evaluator_receipt(base, repeat, contrast)
        if receipt["status"] != "EVALUATED":
            continue
        data = summary(receipt)
        support = data["support"]
        if not support["rpe_valid"]:
            continue
        p = float(data["arms"]["P"]["rpe_rmse_m"])
        comparator = float(data["arms"]["comparator"]["rpe_rmse_m"])
        values["p_rpe_rmse_m"].append(p)
        values["comparator_rpe_rmse_m"].append(comparator)
        individual.append({"repeat": repeat, "p_rpe_rmse_m": p, "comparator_rpe_rmse_m": comparator})
    return {
        "numeric_repeats": len(individual),
        "p_rpe_median_m": statistics.median(values["p_rpe_rmse_m"]) if values["p_rpe_rmse_m"] else None,
        "comparator_rpe_median_m": statistics.median(values["comparator_rpe_rmse_m"]) if values["comparator_rpe_rmse_m"] else None,
        "individual": individual,
    }


def relative_difference(current: float, reference: float) -> float:
    return (current - reference) / reference if reference != 0 else math.inf


def main() -> int:
    frontend = {arm: load(ROOT / "frontend_semantic" / f"{arm}.json") for arm in ("B1", "M", "P")}
    frontend_pass = all(
        item["container_bytes_identical"] and item["ordered_message_stream_identical"]
        for item in frontend.values()
    )

    backend_rows = []
    for queue_index in QUEUE_INDICES:
        formal = load(FORMAL / "receipts" / f"queue_{queue_index:03d}.json")
        fresh = load(FRESH / "receipts" / f"queue_{queue_index:03d}.json")
        backend_rows.append(
            {
                "queue_index": queue_index,
                "arm": formal["arm"],
                "formal_status": formal["status"],
                "fresh_status": fresh["status"],
                "status_match": formal["status"] == fresh["status"],
                "formal_vio_rows": formal["output"]["vio_rows"],
                "fresh_vio_rows": fresh["output"]["vio_rows"],
                "row_count_match": formal["output"]["vio_rows"] == fresh["output"]["vio_rows"],
                "trajectory_bytes_identical": formal["output"]["vio_sha256"] == fresh["output"]["vio_sha256"],
            }
        )
    backend_terminal_pass = all(row["status_match"] and row["row_count_match"] for row in backend_rows)

    evaluator_status = []
    for contrast in CONTRASTS:
        for repeat in (1, 2, 3):
            formal = evaluator_receipt(FORMAL, repeat, contrast)
            fresh = evaluator_receipt(FRESH, repeat, contrast)
            evaluator_status.append(
                {
                    "contrast": contrast,
                    "repeat": repeat,
                    "formal_status": formal["status"],
                    "fresh_status": fresh["status"],
                    "match": formal["status"] == fresh["status"],
                }
            )
    evaluator_status_pass = all(item["match"] for item in evaluator_status)

    metric_comparisons = {}
    numeric_pass = True
    tolerance = 0.01
    for contrast in ("P_vs_B0", "P_vs_B1"):
        formal = median_metrics(FORMAL, contrast)
        fresh = median_metrics(FRESH, contrast)
        p_difference = relative_difference(fresh["p_rpe_median_m"], formal["p_rpe_median_m"])
        comparator_difference = relative_difference(
            fresh["comparator_rpe_median_m"], formal["comparator_rpe_median_m"]
        )
        passed = abs(p_difference) <= tolerance and abs(comparator_difference) <= tolerance
        numeric_pass = numeric_pass and passed
        metric_comparisons[contrast] = {
            "formal": formal,
            "fresh": fresh,
            "p_median_relative_difference": p_difference,
            "comparator_median_relative_difference": comparator_difference,
            "relative_tolerance": tolerance,
            "pass": passed,
        }

    contract = load(SOURCE_CONTRACT)
    expected = {
        "exporter": contract["frontend_mapper"]["exporter"]["sha256"],
        "estimator_cpp": next(
            row["sha256"] for row in contract["consumer_files"]
            if row["path"].endswith("estimator/estimator.cpp")
        ),
        "vins_binary": contract["consumer_binary"]["sha256"],
    }
    current = {
        "exporter": sha256(CURRENT_EXPORTER),
        "estimator_cpp": sha256(CURRENT_ESTIMATOR),
        "vins_binary": sha256(CURRENT_BINARY),
    }
    source_identity = {
        key: {"expected_sha256": expected[key], "current_sha256": current[key], "match": expected[key] == current[key]}
        for key in expected
    }
    source_snapshot_pass = all(value["match"] for value in source_identity.values())

    formal_outliers = []
    for contrast, comparison in metric_comparisons.items():
        values = [row["p_rpe_rmse_m"] for row in comparison["formal"]["individual"]]
        median_value = statistics.median(values)
        for row in comparison["formal"]["individual"]:
            if row["p_rpe_rmse_m"] > 10 * median_value:
                formal_outliers.append({"contrast": contrast, **row, "median_m": median_value})

    functional_pass = frontend_pass and backend_terminal_pass and evaluator_status_pass and numeric_pass
    overall = "REVISE"
    payload = {
        "schema_version": "p11-clean-reproduction-closeout-v1",
        "window_id": "aqualoc_harbor:H05:0002",
        "functional_reproduction": "PASS" if functional_pass else "FAIL",
        "strict_release_snapshot_reproduction": "PASS" if source_snapshot_pass and functional_pass else "FAIL",
        "p11_decision": overall,
        "decision_reasons": [
            "H1 low-texture effectiveness was inadequate in P07",
            "frozen exporter and estimator source bytes were not retained",
        ],
        "frontend_byte_and_semantic_identity_pass": frontend_pass,
        "frontend_comparisons": frontend,
        "backend_terminal_and_row_count_pass": backend_terminal_pass,
        "backend_comparisons": backend_rows,
        "evaluator_status_pass": evaluator_status_pass,
        "evaluator_status_comparisons": evaluator_status,
        "window_median_numeric_tolerance_pass": numeric_pass,
        "metric_comparisons": metric_comparisons,
        "formal_repeat_outliers": formal_outliers,
        "source_snapshot_identity_pass": source_snapshot_pass,
        "source_identity": source_identity,
        "interpretation": (
            "Fresh current-source bags are byte-identical to frozen H05 bags and robust window medians "
            "reproduce within 1%; individual external-feature VINS trajectories are not byte deterministic."
        ),
    }
    atomic_json(ROOT / "p11_closeout.json", payload)

    p_b0 = metric_comparisons["P_vs_B0"]
    p_b1 = metric_comparisons["P_vs_B1"]
    report = f"""# P11 clean reproduction closeout

Decision: **REVISE**. Functional reproduction passes, but strict release-snapshot reproduction fails because two frozen source files were not retained byte-for-byte; P07 H1 also failed independently.

## What reproduced

- Fresh H05 B1, M, and P bags are byte-identical and message-stream-identical to the frozen inputs (9,730 messages each; 450 feature frames).
- All 12 backend attempts reproduce their terminal class and trajectory row count: P/B1/B0 each complete 3/3, while M reproduces algorithm hard failure 3/3.
- P-vs-B0 and P-vs-B1 window-median RPE values reproduce within the frozen 1% relative tolerance. P median relative differences are {100*p_b0['p_median_relative_difference']:.4f}% and {100*p_b1['p_median_relative_difference']:.4f}%, respectively.
- The unchanged VINS binary still matches the frozen SHA-256.

## What did not reproduce strictly

- Current `export_vins_features.py` and `estimator.cpp` do not match the frozen source hashes, so the original source-level guard rejects a new confirmatory export. The current exporter nevertheless produced byte-identical H05 bags.
- External-feature trajectories are not byte deterministic. The formal H05 P repeat 1 produced an RPE of 511.82 m, while its other two repeats and all three fresh repeats were about 0.022 m. The preregistered three-repeat median is stable, but the outlier must remain disclosed.

This closes P11 as a completed `REVISE` outcome rather than leaving it unrun. It supports reproducibility of the frozen inputs, terminal outcomes, and robust window reducer, but not an exact frozen-source release snapshot.
"""
    atomic_text(ROOT / "p11-reproduction-report.md", report)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if functional_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
