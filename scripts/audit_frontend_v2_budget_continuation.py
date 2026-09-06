#!/usr/bin/env python3
"""Read-only v2 accounting audit; never regenerate a bag or overwrite evidence.

The output combines the first eight output-frame rows for every active cell
with next-output evidence for all 14 published lineages. Aggregate gate tags
are deliberately NOT interpreted as the termination cause of a particular ID.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

FROZEN_EXPORTER_SHA = "bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d"
METRIC_KEYS = (
    "selected_feature_index", "frame_index", "tracker_source_histogram",
    "pre_gate_sidecar_total", "final_mirror_input_sidecars",
    "final_mirror_kept_sidecars", "final_mirror_persistence_horizon_blocked",
    "learned_export_benefit_reason",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def classify(row: dict[str, str]) -> str:
    """Return an aggregate description, never a per-ID causal diagnosis."""
    reason = row["learned_export_benefit_reason"].split(":")
    if int(row["final_mirror_persistence_horizon_blocked"]):
        return "FINAL_HORIZON_BLOCKED_AGGREGATE"
    if "online_seed_budget" in reason:
        if int(row["final_mirror_input_sidecars"]) > 0:
            return "BUDGET_TAG_WITH_SURVIVING_PREFINAL_CANDIDATES"
        return "BUDGET_TAG_NO_PREFINAL_CANDIDATES"
    if "online_seed_microburst_no_extend" in reason:
        return "MICROBURST_NO_EXTEND_AGGREGATE"
    if int(row["pre_gate_sidecar_total"]) == 0:
        return "NO_PRE_GATE_SIDECARS_AT_THIS_OUTPUT"
    return "PREFINAL_CANDIDATES_PRESENT_EXACT_ID_UNKNOWN"


def build(paper: Path) -> tuple[list[dict], dict]:
    lineages = [r for r in read_csv(paper / "lineage_diagnostic.csv")
                if r["record_type"] == "learned_lineage"]
    active = [r for r in read_csv(paper / "frontend_audit.csv")
              if int(r["kept_sidecars"]) > 0]
    output, totals = [], []
    for cell in active:
        run = Path(cell["run_dir"])
        receipt = json.loads((run / "frontend_receipt.json").read_text())
        metric_path = run / "frontend_metrics.csv"
        digest = sha(metric_path)
        if digest != receipt["frontend_metrics_sha256"]:
            raise ValueError(f"Metrics identity mismatch: {run}")
        if receipt["exporter_sha256"] != FROZEN_EXPORTER_SHA:
            raise ValueError(f"Exporter identity mismatch: {run}")
        metrics = read_csv(metric_path)
        by_frame = {int(r["selected_feature_index"]): r for r in metrics}
        if len(by_frame) != len(metrics):
            raise ValueError(f"Duplicate selected frame: {run}")
        scope = dict(run_slug=cell["run_slug"], arm=cell["arm"],
                     metrics_sha256=digest)
        for selected in range(8):
            row = by_frame[selected]
            output.append(dict(record_type="frame", **scope,
                               **{key: row[key] for key in METRIC_KEYS},
                               aggregate_evidence=classify(row)))
        members = [r for r in lineages if r["run_slug"] == cell["run_slug"]
                   and r["arm"] == cell["arm"]]
        for lineage in members:
            first = int(lineage["first_published_selected_feature_index"])
            row = by_frame[int(lineage["last_published_selected_feature_index"]) + 1]
            output.append(dict(
                record_type="lineage_next_output", **scope,
                feature_id=lineage["feature_id"],
                published_selected_indices=lineage["published_selected_feature_indices_json"],
                published_observations=int(lineage["published_observations"]),
                # Conditional bound for this observed first-publication time;
                # no backfilling, at most one mono observation per output.
                max_observations_from_same_first_publish_to_frame4=max(0, 5 - first),
                **{key: row[key] for key in METRIC_KEYS},
                aggregate_evidence=classify(row),
                same_id_internal_survival="Unknown",
                exact_id_termination_cause="Unknown",
            ))
        totals.append(dict(**scope, lineages=len(members),
                           prefinal_input_sum=sum(int(r["final_mirror_input_sidecars"]) for r in metrics),
                           published_observations=sum(int(r["final_mirror_kept_sidecars"]) for r in metrics)))
    if len(lineages) != 14 or sum(t["lineages"] for t in totals) != 14:
        raise ValueError("Frozen v2 lineage roster changed")
    singletons = [r for r in output if r.get("published_observations") == 1]
    summary = dict(active_cells=len(active), lineages=len(lineages), cells=totals,
                   singleton_next_output_evidence=dict(Counter(r["aggregate_evidence"] for r in singletons)),
                   lineage_diagnostic_sha256=sha(paper / "lineage_diagnostic.csv"),
                   exporter_sha256=FROZEN_EXPORTER_SHA)
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, summary = build(args.paper)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    # Exclusive creation protects both frozen input and earlier audit outputs.
    with args.output.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
