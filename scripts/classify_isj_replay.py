#!/usr/bin/env python3
"""Classify one replay with the frozen ISJ failure taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.evaluation.failure_classifier import (
    FailureTaxonomy,
    ReplayEvidence,
    read_trajectory_rows,
)


DEFAULT_TAXONOMY = (
    ROOT / "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--vins-log", required=True)
    parser.add_argument("--window-start", type=float, required=True)
    parser.add_argument("--window-end", type=float, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--timed-out", action="store_true")
    parser.add_argument("--input-message-count", type=int)
    parser.add_argument("--processed-message-count", type=int)
    parser.add_argument("--backlog-growth-s", type=float, default=0.0)
    parser.add_argument("--infrastructure-evidence", action="append", default=[])
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    parser.add_argument("--output-json")
    args = parser.parse_args()

    timestamps, finite_rows = read_trajectory_rows(args.trajectory)
    log_text = Path(args.vins_log).read_text(encoding="utf-8", errors="replace")
    taxonomy = FailureTaxonomy.from_yaml(args.taxonomy)
    decision = taxonomy.classify(
        ReplayEvidence(
            process_exit_code=args.exit_code,
            timed_out=args.timed_out,
            window_start_s=args.window_start,
            window_end_s=args.window_end,
            trajectory_timestamps_s=timestamps,
            trajectory_rows_finite=finite_rows,
            log_text=log_text,
            input_message_count=args.input_message_count,
            processed_message_count=args.processed_message_count,
            observable_backlog_growth_s=args.backlog_growth_s,
            infrastructure_evidence=tuple(args.infrastructure_evidence),
        )
    )
    payload = json.dumps(decision.to_dict(), sort_keys=True, indent=2)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
