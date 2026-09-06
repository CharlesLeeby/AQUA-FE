#!/usr/bin/env python3
"""Write the compact SHA-256 manifest for EXP-20260906-009."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_protected_prefill_slot_v1"
)
V2_RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical(path: Path) -> str:
    value = str(path)
    for prefix, replacement in (
        (str(ROOT) + "/", "repo:"),
        (str(RUNTIME) + "/", "prefill_runtime:"),
        (str(V2_RUNTIME) + "/", "v2_runtime:"),
    ):
        if value.startswith(prefix):
            return replacement + value[len(prefix):]
    return value


def main() -> int:
    compact_names = [
        "preregistration.md",
        "development_windows.csv",
        "arms.csv",
        "method_lock.json",
        "frontend_audit.csv",
        "action_audit.csv",
        "exact_fallback.csv",
        "export_only_report.md",
        "decision.json",
        "matched_control_plan.json",
        "matched_control_plan.lock.json",
        "matched_control_audit.csv",
        "backend_replay_plan.csv",
        "backend_execution_lock.json",
        "backend_results_repeats.csv",
        "backend_results.csv",
        "runability.csv",
        "common_support_status.csv",
        "accuracy_repeats.csv",
        "accuracy.csv",
        "backend_comparisons.csv",
        "development_outcomes.csv",
        "v2_vs_prefill_mechanism.csv",
        "backend_config_audit.csv",
        "backend_decision.json",
        "report.md",
    ]
    paths: set[Path] = {PAPER / name for name in compact_names}
    for support in (PAPER / "common_support").glob("*"):
        for name in (
            "common_support_summary.json",
            "common_support_metrics.csv",
            "evo_crosscheck.json",
        ):
            paths.add(support / name)
    with (PAPER / "backend_replay_plan.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        for row in csv.DictReader(stream):
            paths.add(Path(row["feature_bag"]))
            replay = Path(row["replay_dir"])
            paths.add(replay / "replay_receipt.txt")
            paths.add(replay / "vins_output/vio.csv")
            paths.add(replay / "vins.log")
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(
            "manifest inputs missing: " + "; ".join(map(str, missing))
        )
    output = PAPER / "artifacts.sha256"
    with output.open("w", encoding="utf-8") as stream:
        for path in sorted(paths, key=logical):
            stream.write(f"{sha256(path)}  {logical(path)}\n")
    print(f"wrote {len(paths)} entries to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
